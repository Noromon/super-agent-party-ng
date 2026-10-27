# -*- coding: utf-8 -*-
"""M5-XMPP 第九 bot 通道（收编 xmpp-bridge 扩展，直连 /v1 agent 内核）。

家族结构照搬 TelegramClient：memoryList + AsyncOpenAI 自调用本机 /v1
（asyncToolsID/fileLinks/is_app_bot 契约）+ 分隔符分段发送。
XMPP 侧：slixmpp（TCP 5222 / TLS 5223；wss 传输不支持并给出明确报错）、
XEP-0066 OOB 与内联 base64 收图、XEP-0363 HTTP Upload + SIMS 发图。
安全：外发本地图片仅限 UPLOAD_FILES_DIR / TOOL_TEMP_DIR / KB_DIR 围栏内；
扩展的 local-image?path= 任意文件读 fallback 已废除（上传失败只发文字，
S72 起附具体原因；363 服务多候选重试、CA 证书直放、同指纹证书免复审）。
"""
import asyncio
import base64
import logging
import os
import re
import time
import uuid
from typing import Dict, List, Optional
from urllib.parse import urlparse

import aiohttp
import slixmpp
from openai import AsyncOpenAI
from slixmpp.xmlstream import ET

from py.behavior_engine import BehaviorItem
from py import xmpp_trust
from py.auth import path_under
from py import get_setting as gs_mod
from py.get_setting import (KB_DIR, TOOL_TEMP_DIR, UPLOAD_FILES_DIR,
                            get_port, load_settings)

UPLOAD_NS = "urn:xmpp:http:upload:0"
SIMS_NS = "urn:xmpp:sims:1"
REF_NS = "urn:xmpp:reference:0"
FT_NS = "urn:xmpp:jingle:apps:file-transfer:5"
OOB_NS = "jabber:x:oob"
DISCO_ITEMS_NS = "http://jabber.org/protocol/disco#items"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
# 表示“该候选 JID 上没有 363 服务”的 stanza 错误条件：换下一个候选；全中才判服务器缺失
NO_SERVICE = frozenset(("service-unavailable", "remote-server-not-found",
                        "item-not-found", "feature-not-implemented"))


def pick_upload_services(items, domain):
    """S72: ordered XEP-0363 service candidates. items = [(jid, name), ...]
    disco hits first (in disco order), then the three conventional names."""
    hit = [jid for jid, nm in items
           if jid and ("upload" in jid.lower() or "upload" in (nm or "").lower())]
    out = list(dict.fromkeys(hit))
    for c in (f"httpfileupload.{domain}", f"fileupload.{domain}", f"upload.{domain}"):
        if c not in out:
            out.append(c)
    return out


def build_slot_request(name, size):
    """<size> dual form: XEP-strict servers read the attribute, Openfire
    reads the text (probe-proven); attribute-only gets a 400 there."""
    req = ET.Element("{%s}request" % UPLOAD_NS)
    fn = ET.SubElement(req, "filename", {"name": name})
    fn.text = name
    sz = ET.SubElement(req, "size", {"size": str(size)})
    sz.text = str(size)
    return req


def build_file_share(url, name, size, mime):
    """S76: 与桥接 ext/xmpp-bridge 同构的附件结构（reference/media-sharing
    + 顶层 jabber:x:oob）——Monocles 等客户端按此检测附件；XEP 样例的
    <share><preview> 写法客户端不认（20:01 实测只收到 body 文字）。
    子元素显式标同父命名空间 = 桥接原始串里默认命名空间继承的等价形式。"""
    ref = ET.Element("{%s}reference" % REF_NS, {"type": "data"})
    media = ET.SubElement(ref, "{%s}media-sharing" % SIMS_NS)
    file_el = ET.SubElement(media, "{%s}file" % FT_NS)
    ET.SubElement(file_el, "{%s}name" % FT_NS).text = name
    ET.SubElement(file_el, "{%s}media-type" % FT_NS).text = mime
    ET.SubElement(file_el, "{%s}size" % FT_NS).text = str(size)
    sources = ET.SubElement(media, "{%s}sources" % SIMS_NS)
    ET.SubElement(sources, "{%s}reference" % REF_NS, {"uri": url, "type": "data"})
    oob = ET.Element("{%s}x" % OOB_NS)
    ET.SubElement(oob, "{%s}url" % OOB_NS).text = url
    ET.SubElement(oob, "{%s}size" % OOB_NS).text = str(size)
    ET.SubElement(oob, "{%s}name" % OOB_NS).text = name
    return [ref, oob]


def slot_error_kind(xml) -> str:
    """'noservice' -> try next candidate; 'error' -> one-shot failure."""
    try:
        err = xml.find("{*}error")
    except Exception:
        return "error"
    if err is None:
        return "error"
    for child in err:
        if (child.tag.rsplit("}", 1)[-1] or "").lower() in NO_SERVICE:
            return "noservice"
    return "error"


def system_tls_ok(host, port) -> bool:
    """Endpoint validates against the OS trust store (CA-issued cert) ->
    pass the HTTPS gate without TOFU review."""
    import socket
    import ssl
    try:
        with socket.create_connection((host, port), 8) as s:
            with ssl.create_default_context().wrap_socket(s, server_hostname=host):
                return True
    except Exception:
        return False



from py import llm_gate
from py.im_empty_guard import empty_reply_msg, error_from_delta, log_empty_reply


class XmppClient:
    PLUGINS = ("xep_0030", "xep_0066", "xep_0199")

    def __init__(self):
        self.XmppAgent = "super-model"
        self.memoryLimit = 10
        self.memoryList: Dict[str, List[Dict]] = {}     # bare jid -> messages
        self.asyncToolsID: Dict[str, List[str]] = {}
        self.fileLinks: Dict[str, List[str]] = {}
        self.separators = ["。", "\n", "？", "！"]
        self.reasoningVisible = False
        self.quickRestart = True
        self.wakeWord = None
        self.bot_username = ""
        self.bot_password = ""
        self.domain = "localhost"
        self.service_url = "tcp://localhost:5222"
        self.ignore_cert_hosts = []
        self.extra_outbound_dirs = []
        self.tools_mode = "inherit"      # inherit | whitelist | blacklist
        self.tools_list = []
        self.image_resize_mode = "downscale_only"   # off | fit | downscale_only
        self.image_max_side = 1024
        self.image_oversize_action = "reject"   # off | reject | shrink
        self.image_max_mb = 20
        self.config = None
        self._is_ready = False
        self._manager_ref = None
        self.behaviorTargetJids: List[str] = []
        self._ready_callback = None
        self._shutdown_requested = False
        self.xmpp: Optional[slixmpp.Client] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self._upload_service_jid: Optional[str] = None
        self._xep0363_supported = True
        self._ready_future: Optional[asyncio.Future] = None

        from py.behavior_engine import global_behavior_engine
        global_behavior_engine.register_handler("xmpp", self.execute_behavior_event)

    # -------------------- 生命周期 --------------------
    async def run(self):
        if not self.bot_username or not self.bot_password or not self.domain:
            raise RuntimeError("XMPP 配置不完整（需要用户名/密码/域名）")
        jid = f"{self.bot_username}@{self.domain}"
        host, port, use_ssl = self._parse_service(self.service_url)  # fail before any I/O
        # TLS verification is delegated to the application-level TOFU hook
        # (ssl_cert); connector ssl=False lets every request carry its own ssl ctx.
        self._tls_key = f"{host}:{port}"
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60),
            # ThreadedResolver: aiodns (slixmpp dep) skips hosts files and
            # NetBIOS names — plain socket resolution is what users expect.
            connector=aiohttp.TCPConnector(ssl=False, resolver=aiohttp.ThreadedResolver()))

        self.xmpp = slixmpp.ClientXMPP(jid, self.bot_password,
                                       ssl_context=xmpp_trust.insecure_client_context())
        for plug in self.PLUGINS:
            self.xmpp.register_plugin(plug)  # disco(0030) / OOB(0066) / keepalive(0199)
        self.xmpp.auto_reconnect = True
        self.xmpp.add_event_handler("session_start", self._on_session_start)
        self.xmpp.add_event_handler("ssl_cert", self._on_ssl_cert)
        self.xmpp.add_event_handler("message", self._on_message)
        self.xmpp.add_event_handler("disconnected", self._on_disconnected)

        self._ready_future = asyncio.get_running_loop().create_future()
        # slixmpp 1.17: TLS via switches; connect(host, port) returns a
        # background retry future (never await it) — readiness comes from
        # session_start, bounded by the 30 s wait below.
        self.xmpp.enable_direct_tls = bool(use_ssl)
        self.xmpp.enable_starttls = not use_ssl
        self.xmpp.enable_plaintext = False
        self.xmpp.connect(host=host, port=port)
        await asyncio.wait_for(self._ready_future, timeout=30)

        try:
            while not self._shutdown_requested:
                await asyncio.sleep(0.5)
        finally:
            try:
                self.xmpp.disconnect()
            except Exception:
                pass
            if self.session:
                await self.session.close()
                self.session = None

    @staticmethod
    def _parse_service(service_url: str):
        u = urlparse(service_url if "://" in service_url else "tcp://" + service_url)
        if u.scheme in ("ws", "wss"):
            raise RuntimeError(
                f"XMPP WebSocket 传输 ({service_url}) 暂不支持，请改用 tcp://host:5222 或 xmpps://host:5223")
        default_port = 5223 if u.scheme == "xmpps" else 5222
        return u.hostname or "localhost", u.port or default_port, u.scheme == "xmpps"

    async def _on_session_start(self, _event):
        self.xmpp.send_presence()
        try:
            await self.xmpp.get_roster()
        except Exception:
            pass
        self._is_ready = True
        logging.info("XMPP bot 会话就绪: %s@%s", self.bot_username, self.domain)
        if self._manager_ref:
            manager = self._manager_ref()
            if manager:
                manager._ready_complete.set()
                manager.is_running = True
        if self._ready_future and not self._ready_future.done():
            self._ready_future.set_result(True)

    def _on_disconnected(self, _event):
        self._is_ready = False
        logging.warning("XMPP bot 连接断开（slixmpp 将自动重连）")

    # -------------------- TLS / TOFU --------------------
    def _on_ssl_cert(self, pem):
        """Application-level certificate enforcement (fail-closed)."""
        try:
            key = getattr(self, "_tls_key", "") or "?"
            host = key.split(":")[0]
            if xmpp_trust.host_allowed(host, self.ignore_cert_hosts):
                logging.warning("XMPP TLS: %s 命中证书豁免白名单（用户显式配置）", key)
                return
            fp = xmpp_trust.fingerprint_pem(pem)
            if xmpp_trust.get_store().check(key, fp) == "match":
                return
            if xmpp_trust.ONCE.is_granted(key):
                return
            xmpp_trust.PENDING.add(key, fp, pem)
            logging.warning("XMPP 证书未获信任，已断开待审阅: %s %s", key, fp)
            self.xmpp.disconnect()
        except Exception:
            logging.exception("XMPP ssl_cert 处理异常，按不可信处理")
            try:
                self.xmpp.disconnect()
            except Exception:
                pass

    def _aio_ssl(self, url: str):
        """Per-request ssl ctx for XEP-0363 PUTs: TOFU-known or whitelisted
        hosts get a non-verifying context; everything else verifies normally."""
        host = urlparse(url).hostname or ""
        if (xmpp_trust.host_allowed(host, self.ignore_cert_hosts)
                or xmpp_trust.get_store().knows_host(host)):
            return xmpp_trust.insecure_client_context()
        return True

    async def _gate_https(self, url: str) -> bool:
        """TOFU gate for ad-hoc HTTPS endpoints (file upload/download host).
        Whitelisted or already-trusted hosts pass; an unknown certificate is
        probed and queued into the same review store as the XMPP connection,
        and the request is refused until reviewed."""
        u = urlparse(url)
        if u.scheme != "https":
            return True
        host, port = u.hostname or "", u.port or 443
        key = f"{host}:{port}"
        if xmpp_trust.host_allowed(host, self.ignore_cert_hosts):
            return True
        # host-level trust carries to sibling ports on the same machine
        # (Typical: prosody 5222 + http-upload 7443 share one self-signed cert)
        if xmpp_trust.get_store().knows_host(host):
            return True
        # S72: CA 证书（系统信任链可验）直接放行，无需 TOFU 审阅
        if await asyncio.to_thread(system_tls_ok, host, port):
            return True
        try:
            _r, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port,
                                        ssl=xmpp_trust.insecure_client_context()), 10)
            try:
                der = writer.get_extra_info("ssl_object").getpeercert(True)
                pem = ("-----BEGIN CERTIFICATE-----\n"
                       + base64.encodebytes(der).decode()
                       + "-----END CERTIFICATE-----\n")
            finally:
                writer.close()
            fp = xmpp_trust.fingerprint_pem(pem)
        except Exception as e:
            logging.getLogger("app").warning("XMPP TLS 探测失败 %s: %r", key, e)
            return False
        if (xmpp_trust.get_store().check(key, fp) == "match"
                or xmpp_trust.ONCE.is_granted(key)):
            return True
        # S72: 同一张已审阅过的证书（同指纹）出现在其它 host:port（Openfire
        # slot 回机器名:7443 而非连接用的 localhost:5222）——视为已信任
        if any((v.get("fingerprint") or "") == fp
               for v in xmpp_trust.get_store().entries().values()):
            return True
        xmpp_trust.PENDING.add(key, fp, pem)
        logging.getLogger("app").warning("XMPP 文件主机证书待审阅: %s %s", key, fp)
        return False
        if (xmpp_trust.get_store().check(key, fp) == "match"
                or xmpp_trust.ONCE.is_granted(key)):
            return True
        xmpp_trust.PENDING.add(key, fp, pem)
        logging.warning("XMPP 文件主机证书待审阅: %s %s", key, fp)
        return False

    # -------------------- 会话持久化（"手机"行级存储） --------------------
    @staticmethod
    def _conv_key(chat_jid: str) -> str:
        return f"bot:xmpp:{chat_jid}"

    async def _restore_conv(self, chat_jid: str) -> list:
        try:
            saved = await gs_mod.load_bot_conv(self._conv_key(chat_jid))
            if saved:
                logging.info("XMPP 会话从持久化恢复: %s (%d 条)", chat_jid, len(saved))
                return saved
        except Exception:
            logging.warning("XMPP 会话恢复失败（转纯内存模式）", exc_info=True)
        return []

    async def _persist_conv(self, chat_jid: str):
        try:
            await gs_mod.save_bot_conv(self._conv_key(chat_jid),
                                       self.memoryList.get(chat_jid, []))
        except Exception:
            logging.warning("XMPP 会话持久化失败（本回合仅内存）", exc_info=True)

    # -------------------- 收图内联（本地模型不会拉远程 url） --------------------
    @staticmethod
    def _resize_if_needed(data: bytes, ctype: str, mode: str, max_side: int):
        """Scale the image that goes into the model request only (the copy
        saved to disk keeps the original bytes).
        mode: off | fit (force long side to max_side) | downscale_only
        (never enlarge). Any failure falls through to the original bytes."""
        if mode not in ("fit", "downscale_only") or max_side < 16:
            return data, ctype
        try:
            import io as _io
            from PIL import Image
            img = Image.open(_io.BytesIO(data))
            img.load()
            w, h = img.size
            longest = max(w, h)
            if longest <= 0:
                return data, ctype
            if mode == "downscale_only" and longest <= max_side:
                return data, ctype
            if mode == "fit" and longest == max_side:
                return data, ctype
            scale = max_side / longest
            nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
            img = img.resize((nw, nh), Image.LANCZOS)
            has_alpha = (img.mode in ("RGBA", "LA", "PA")
                         or (img.mode == "P" and "transparency" in img.info))
            buf = _io.BytesIO()
            if has_alpha or ctype == "image/png":
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
                img.save(buf, "PNG")
                out_ctype = "image/png"
            else:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(buf, "JPEG", quality=85)
                out_ctype = "image/jpeg"
            out = buf.getvalue()
            if mode == "downscale_only" and len(out) >= len(data):
                return data, ctype   # 重编码无收益，保留原图
            return out, out_ctype
        except Exception:
            logging.warning("图片缩放跳过（PIL 失败），按原图进入请求", exc_info=True)
            return data, ctype

    _HARD_MAX_BYTES = 512 * 1024 * 1024   # 内存安全垫（仅 off 模式生效）

    @staticmethod
    def _validate_image(data: bytes) -> bool:
        """Strict decode check + container-level end signature (PIL is far
        too lenient about truncated PNG/GIF). Fail-closed on any doubt."""
        try:
            import io as _io
            from PIL import Image
            img = Image.open(_io.BytesIO(data))
            img.load()
        except Exception:
            return False
        try:
            if data[:8] == b"\x89PNG\r\n\x1a\n":
                return b"IEND" in data[-16:]
            if data[:2] == b"\xff\xd8":                      # JPEG: EOI near EOF
                return b"\xff\xd9" in data[-32:]
            if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
                declared = int.from_bytes(data[4:8], "little") + 8
                return abs(declared - len(data)) <= 1        # RIFF length invariant
            if data[:3] == b"GIF":
                return data[-1:] == b"\x3b"                  # GIF trailer
            if data[:2] == b"BM" and len(data) >= 6:
                declared = int.from_bytes(data[2:6], "little")
                return declared == 0 or abs(declared - len(data)) <= 1024
        except Exception:
            return False
        return True

    @staticmethod
    def _shrink_to_bytes(data: bytes, max_bytes: int):
        """Lossless-PNG downsweep (LANCZOS x0.7 steps, long-side floor 256)
        until the image fits max_bytes; the result is treated as the new
        'original' for every downstream step. None = could not fit / broken."""
        import io as _io
        from PIL import Image
        try:
            img = Image.open(_io.BytesIO(data))
            img.load()
            has_alpha = (img.mode in ("RGBA", "LA", "PA")
                         or (img.mode == "P" and "transparency" in img.info))
            if has_alpha and img.mode != "RGBA":
                img = img.convert("RGBA")
            for _ in range(12):
                buf = _io.BytesIO()
                img.save(buf, "PNG")
                out = buf.getvalue()
                if len(out) <= max_bytes:
                    return out, "image/png"
                w, h = img.size
                longest = max(w, h)
                if longest <= 256:
                    return None
                scale = max(256.0 / longest, 0.7)
                img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                                 Image.LANCZOS)
            return None
        except Exception:
            logging.warning("无损缩至门槛失败", exc_info=True)
            return None

    async def _download_as_data_uri(self, url: str):
        """Returns (data_uri, saved_filename); (None, None) on any refusal.
        Streams to completion (aiohttp content.read(n) is a partial read!),
        then gate -> oversize policy -> disk -> request-resize."""
        if not await self._gate_https(url):
            return None, None
        action = self.image_oversize_action if self.image_oversize_action in ("off", "reject", "shrink") else "reject"
        max_bytes = max(1, int(self.image_max_mb or 20)) * 1024 * 1024
        try:
            async with self.session.get(url, ssl=self._aio_ssl(url)) as resp:
                if resp.status != 200:
                    return None, None
                ctype = (resp.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
                if not ctype.startswith("image/"):
                    ctype = "image/jpeg"
                buf = bytearray()
                async for chunk in resp.content.iter_chunked(65536):
                    buf.extend(chunk)
                    if action == "reject" and len(buf) > max_bytes:
                        logging.warning("XMPP 图片超门槛拒绝(读取掐断) %s: >%d bytes", url, max_bytes)
                        return None, None
                    if len(buf) > self._HARD_MAX_BYTES:
                        logging.warning("XMPP 图片超内存安全垫拒绝 %s: >%d bytes", url, self._HARD_MAX_BYTES)
                        return None, None
                data = bytes(buf)
        except Exception as e:
            logging.warning("XMPP 图片下载失败 %s: %s", url, e)
            return None, None
        # 完整性闸门（fail-closed）：截断/坏图不进落盘、不进请求
        if not self._validate_image(data):
            logging.warning("XMPP 图片完整性校验失败(%d bytes)，已丢弃: %s", len(data), url)
            return None, None
        # 超限缩小：无损 PNG 迭代缩至门槛内，此后当"原图"用
        if action == "shrink" and len(data) > max_bytes:
            shrunk = self._shrink_to_bytes(data, max_bytes)
            if shrunk is None:
                logging.warning("XMPP 图片无法无损缩至门槛(%d bytes)，已拒绝: %s", max_bytes, url)
                return None, None
            data, ctype = shrunk
        # keep a copy in UPLOAD_FILES_DIR so tools/history can re-open it
        fname = None
        try:
            fname = f"xmpp_in_{int(time.time() * 1000)}.{ctype.rsplit('/', 1)[-1]}"
            with open(os.path.join(UPLOAD_FILES_DIR, fname), "wb") as f:
                f.write(data)
        except OSError:
            fname = None
        send_data, send_ctype = self._resize_if_needed(
            data, ctype, self.image_resize_mode, self.image_max_side)
        return (f"data:{send_ctype};base64,"
                + base64.b64encode(send_data).decode()), fname

    async def _inline_remote_images(self, content):
        """http(s) image parts -> downloaded base64 data URIs; failures keep
        an explicit text notice instead of a url the model cannot open."""
        if not isinstance(content, list):
            return content
        out = []
        for part in content:
            url = None
            if isinstance(part, dict) and part.get("type") == "image_url":
                url = str((part.get("image_url") or {}).get("url", ""))
            if url and url.lower().startswith(("http://", "https://")):
                data_uri, fname = await self._download_as_data_uri(url)
                if data_uri:
                    out.append({"type": "image_url", "image_url": {"url": data_uri},
                                "_saved": fname or ""})
                else:
                    out.append({"type": "text", "text":
                                f"[图片下载失败（可能原因：自签名主机需先在 SAP 设置→XMPP 卡片信任证书、"
                                f"图片截断损坏、或超出大小门槛）。原始URL: {url}]"})
            else:
                out.append(part)
        return out

    @staticmethod
    def _redact_media_for_store(content, text: str = "") -> dict:
        """DB/history copy of a multimodal turn: heavy base64 dropped, short
        marker kept (with the saved filename so tools can re-open the image).
        The full data URI only ever lives in the live request."""
        if not isinstance(content, list):
            return {"role": "user", "content": content}
        parts, names = [], []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "image_url":
                if p.get("_saved"):
                    names.append(p["_saved"])
                continue
            parts.append(p)
        txt = " ".join(x.get("text", "") for x in parts
                       if isinstance(x, dict) and x.get("type") == "text").strip()
        body = txt or text or ""
        if len(parts) < len(content):  # images were dropped
            tag = "[用户发送了图片" + (f"，已存文件: {', '.join(names)}" if names else "") + "]"
            body = f"{tag} {body}".strip()
        return {"role": "user", "content": body or "[图片消息]"}

    # -------------------- 工具环境分离（本渠道降级） --------------------
    def _tools_override(self) -> dict:
        lst = [t for t in (self.tools_list or []) if t]
        if lst and self.tools_mode == "whitelist":
            return {"enable_tools": lst}
        if lst and self.tools_mode == "blacklist":
            return {"disable_tools": lst}
        return {}

    # -------------------- 消息入口 --------------------
    def _on_message(self, msg):
        try:
            asyncio.create_task(self._handle_message(msg))
        except RuntimeError:
            logging.warning("XMPP 消息处理未启动（事件循环不可用）")

    async def _handle_message(self, msg):
        if msg.get("type") == "groupchat":
            return
        frm = str(msg.get_from().bare) if msg.get_from() else ""
        if not frm or frm.split("@")[0] == self.bot_username:
            return
        text = (msg.get("body") or "").strip()

        from py.behavior_engine import global_behavior_engine
        global_behavior_engine.report_activity("xmpp", frm)

        if self.quickRestart and text in {"/restart", "/重启", "/new"}:
            self.memoryList[frm] = []
            await self._persist_conv(frm)
            await self._send_text(frm, "对话记录已重置，开始新话题吧！")
            return
        if text.lower() == "/id":
            await self._send_text(frm, f"当前 JID（用于自主行为目标列表）:\n{frm}")
            return
        if text.lower() == "/help":
            await self._send_text(frm, "/new 清空对话  /id 查看目标ID  /help 帮助")
            return
        # A11 IM 快捷指令（上游 3e58049f fork 适配：fork 无本地任务表，/stop 仅回执）
        from py import shortcut_commands
        if await shortcut_commands.im_shortcuts_enabled():
            _act = shortcut_commands.parse_im_action(text)
            if _act:
                if _act == "stop":
                    await self._send_text(frm, shortcut_commands.STOP_MSG_ZH)
                elif _act == "reset":
                    self.memoryList[frm] = []
                    await self._persist_conv(frm)
                    await self._send_text(frm, shortcut_commands.RESET_MSG_ZH)
                elif _act == "help":
                    await self._send_text(frm, shortcut_commands.build_help_text("zh"))
                elif _act == "skills":
                    await self._send_text(frm, await shortcut_commands.build_skills_text("zh"))
                elif _act == "model":
                    await self._send_text(frm, await shortcut_commands.handle_model_command(text, "zh"))
                elif _act == "personality":
                    await self._send_text(frm, await shortcut_commands.handle_personality_command(text, "zh"))
                elif _act == "retry":
                    await self._send_text(frm, shortcut_commands.retry_hint("zh"))
                elif _act == "mode":
                    await self._send_text(frm, await shortcut_commands.build_mode_info_text("zh"))
                return
        if self.wakeWord and self.wakeWord not in text:
            return

        images, text = self._extract_incoming_images(msg, text)
        if images:
            content = [{"type": "image_url", "image_url": {"url": uri}} for uri in images]
            content.append({"type": "text", "text": text or "用户发送了一张图片"})
            await self._process_llm(frm, "", content)
        else:
            await self._process_llm(frm, text, [])

    _IMG_URL_RE = re.compile(
        r"https?://[^\s<>\"'\)\]]+"
        r"(?:\.(?:jpg|jpeg|png|gif|webp|bmp)(?:\?[^\s<>\"'\)\]]*)?|/httpfileupload[^\s<>\"'\)\]]*)",
        re.IGNORECASE)

    def _extract_incoming_images(self, msg, text):
        """Collect image URIs (OOB extension, body text, inline base64).
        Many mobile clients embed upload links in the plain body instead of
        XEP-0066 — body links are stripped so the model never sees raw urls
        it cannot resolve; the download+inline pipeline handles them."""
        uris: List[str] = []
        try:  # XEP-0066 OOB
            oob = msg.get("oob", None)
            if oob is not None:
                for url in oob.get("urls", []) or []:
                    if isinstance(url, str) and url.lower().startswith(("http://", "https://")):
                        uris.append(url)
        except Exception:
            pass
        if text:
            for m in self._IMG_URL_RE.finditer(text):
                if m.group(0) not in uris:
                    uris.append(m.group(0))
                text = text.replace(m.group(0), " ")
        for m in re.finditer(r"data:image/(\w+);base64,([A-Za-z0-9+/=]{200,})", text or ""):
            uris.append(m.group(0))
            text = text.replace(m.group(0), " ")
        text = re.sub(r"\s{2,}", " ", text or "").strip()
        return uris[:4], text

    # -------------------- LLM 内核（/v1 自调用，全 agent 能力） --------------------
    @llm_gate.gated
    async def _process_llm(self, chat_jid: str, text: str, extra_content: List[dict]):
        if chat_jid not in self.memoryList:
            self.memoryList[chat_jid] = await self._restore_conv(chat_jid)
        self.asyncToolsID.setdefault(chat_jid, [])
        self.fileLinks.setdefault(chat_jid, [])
        extra_content = await self._inline_remote_images(extra_content)
        if extra_content:
            store_msg = self._redact_media_for_store(extra_content)
            send_content = [{k: v for k, v in p.items() if k != "_saved"}
                            if isinstance(p, dict) else p for p in extra_content]
            user_msg = {"role": "user", "content": send_content}
        else:
            user_msg = store_msg = {"role": "user", "content": text}
        # S89-C：上一轮空回复后重发同文本 → 不在历史里重复堆积（三连重试 ×N 膨胀）
        _flags = self.__dict__.setdefault("_empty_reply_flags", {})
        _last = self.memoryList[chat_jid][-1] if self.memoryList[chat_jid] else None
        if not (_last is not None and _last.get("role") == "user"
                and _last.get("content") == store_msg.get("content")
                and _flags.get(chat_jid)):
            self.memoryList[chat_jid].append(store_msg)
        history = [*self.memoryList[chat_jid][:-1], user_msg]

        settings = await load_settings()
        client = AsyncOpenAI(api_key="super-secret-key",
                             base_url=f"http://127.0.0.1:{get_port()}/v1")
        out_buffer = ""
        full_text = []
        reasoning_chars = 0
        finish_reason = ""
        err_text = ""
        try:
            stream = await client.chat.completions.create(
                model=self.XmppAgent,
                messages=history,
                stream=True,
                extra_body={
                    "asyncToolsID": self.asyncToolsID[chat_jid],
                    "fileLinks": self.fileLinks[chat_jid],
                    "is_app_bot": True,
                    "platform": "xmpp",
                    "peer_id": chat_jid,  # S145：对端身份注入
                    **self._tools_override(),
                },
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                finish_reason = chunk.choices[0].finish_reason or finish_reason
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", "") or ""
                reasoning = getattr(delta, "reasoning_content", "") or ""
                reasoning_chars += len(reasoning)
                tool_link = getattr(delta, "tool_link", "") or ""
                async_tool_id = getattr(delta, "async_tool_id", "") or ""
                if not err_text:
                    err_text = error_from_delta(delta)  # S89-B：流内错误帧不再沉默
                if tool_link and settings["tools"]["toolMemorandum"]["enabled"]:
                    self.fileLinks[chat_jid].append(tool_link)
                if async_tool_id:
                    lst = self.asyncToolsID[chat_jid]
                    if async_tool_id in lst:
                        lst.remove(async_tool_id)
                    else:
                        lst.append(async_tool_id)
                seg = reasoning if (self.reasoningVisible and reasoning) else content
                full_text.append(content)
                if seg:
                    out_buffer += seg
                    out_buffer, ready = self._flush_segments(out_buffer)
                    for piece in ready:
                        await self._send_text(chat_jid, piece)
        except Exception as e:
            logging.error(f"XMPP LLM 调用失败: {e}")
            await self._send_text(chat_jid, f"⚠️ Agent 调用失败: {e}")
            return

        assistant_text = "".join(full_text)
        if not assistant_text.strip():
            log_empty_reply("xmpp", chat_jid, reasoning_chars, finish_reason)
            # S89-B/C：带流内错误摘要如实告知；标记本轮空回复供重发去重
            self.__dict__.setdefault("_empty_reply_flags", {})[chat_jid] = True
            await self._send_text(chat_jid, empty_reply_msg(err_text))
            return
        self.__dict__.setdefault("_empty_reply_flags", {})[chat_jid] = False
        self.memoryList[chat_jid].append({"role": "assistant", "content": assistant_text})
        if self.memoryLimit > 0:
            while len(self.memoryList[chat_jid]) > self.memoryLimit * 2:
                self.memoryList[chat_jid].pop(0)
                if self.memoryList[chat_jid]:
                    self.memoryList[chat_jid].pop(0)
        await self._persist_conv(chat_jid)

        if out_buffer.strip():
            await self._send_text(chat_jid, out_buffer.strip())
        await self._send_local_images(chat_jid, assistant_text)

    def _flush_segments(self, buffer: str):
        """切出可直接发送的完整片段，返回 (剩余缓冲, 就绪片段)。"""
        ready = []
        if len(buffer) > 3500:  # 过长：在分隔符边界强切
            cut = -1
            for sep in self.separators:
                idx = buffer.rfind(sep, 0, 3500)
                if idx != -1:
                    cut = max(cut, idx + len(sep))
            cut = cut if cut != -1 else 3500
            ready.append(buffer[:cut])
            buffer = buffer[cut:]
        if buffer.count("```") % 2 == 0:  # 代码块闭合才按分隔符切完整句
            best = -1
            for sep in self.separators:
                idx = buffer.rfind(sep)
                if idx != -1:
                    best = max(best, idx + len(sep))
            if best != -1:
                ready.append(buffer[:best])
                buffer = buffer[best:]
        return buffer, [r.strip() for r in ready if r.strip()]

    # -------------------- 发送封装 --------------------
    async def _send_text(self, chat_jid: str, text: str):
        if not self.xmpp or not text.strip():
            return
        try:
            self.xmpp.send_message(mto=chat_jid, mbody=text.strip(), mtype="chat")
        except Exception as e:
            logging.getLogger("app").error(f"XMPP 发送失败: {e}")

    def _fence_ok(self, path: str, extra_roots=()) -> bool:
        roots = [UPLOAD_FILES_DIR, TOOL_TEMP_DIR, KB_DIR] + [r for r in extra_roots if r]
        return path_under(path, roots)

    async def _fence_roots(self):
        roots = [os.getcwd()]
        roots += [str(d).strip() for d in (self.extra_outbound_dirs or []) if str(d).strip()]
        try:
            settings = await load_settings()
            cc = str(((settings.get("CLISettings") or {}).get("cc_path") or "")).strip()
            if cc:
                roots.append(cc)
        except Exception:
            pass
        return roots

    async def _send_local_images(self, chat_jid: str, full_text: str):
        roots = await self._fence_roots()
        for m in re.finditer(r"([A-Za-z]:[\\/][^\s|\"'<>\[\]]+|/[^\s|\"'<>\[\]]+)"
                             r"(" + "|".join(re.escape(e) for e in IMAGE_EXTS) + r")",
                             full_text, re.IGNORECASE):
            raw = m.group(0)
            if not self._fence_ok(raw, roots):
                logging.getLogger("app").warning("[XMPP] 拒绝外发围栏外路径: %s", raw)
                continue
            if not os.path.isfile(raw):
                continue
            if not self._xep0363_supported:
                await self._send_text(chat_jid, f"（图片暂无法上传：{os.path.basename(raw)}，"
                                                "服务器 XEP-0363 不可用）")
                continue
            try:
                url = await self._upload_and_share(chat_jid, raw)
                if not url:
                    # 具体原因已由 _upload_and_share 发文字并记 app 日志
                    pass
            except Exception as e:
                logging.getLogger("app").error("[XMPP] 图片外发失败: %r", e, exc_info=True)
                await self._send_text(chat_jid, f"（图片上传失败：{os.path.basename(raw)}，{e}）")

    async def _upload_and_share(self, chat_jid: str, file_path: str) -> Optional[str]:
        size = os.path.getsize(file_path)
        name = os.path.basename(file_path)
        mime = "image/" + name.rsplit(".", 1)[-1].lower().replace("jpg", "jpeg")
        app = logging.getLogger("app")
        reasons = []
        for service in await self._discover_upload_services():
            put_url, get_url, kind = await self._request_slot(service, name, size)
            if not put_url:
                reasons.append(f"{service}:{kind or 'no-slot'}")
                continue
            if not await self._gate_https(put_url):
                u = urlparse(put_url)
                hp = f"{u.hostname}:{u.port or 443}"
                app.warning("[XMPP] 图片上传被拒：上传主机 %s 证书未获信任（已入待审阅）", hp)
                await self._send_text(chat_jid, f"（图片上传被拒：上传主机 {hp} 证书未获信任，"
                                                "请在 SAP 设置→XMPP 卡片完成证书审阅，"
                                                "或将其加入证书豁免白名单）")
                return None
            with open(file_path, "rb") as f:
                data = f.read()
            async with self.session.put(put_url, data=data,
                                        ssl=self._aio_ssl(put_url),
                                        headers={"Content-Type": "application/octet-stream"}) as resp:
                if resp.status not in (200, 201):
                    app.warning("[XMPP] XEP-0363 PUT 返回 HTTP %s（%s）", resp.status, name)
                    await self._send_text(chat_jid, f"（图片上传失败：存储服务器返回 HTTP {resp.status}）")
                    return None
            self._upload_service_jid = service
            app.info("[XMPP] 图片已上传: %s (%s)", get_url, name)
            self._send_sims(chat_jid, get_url, name, size, mime)
            return get_url
        if reasons and all(r.endswith(":noservice") for r in reasons):
            self._xep0363_supported = False
            why = "服务器未启用 XEP-0363"
        else:
            why = "上传服务暂不可用"
        app.warning("[XMPP] 图片上传失败：%s（%s）", why, "; ".join(reasons))
        await self._send_text(
            chat_jid, f"（图片上传失败：{why}；{'，'.join(r.split(':')[0] for r in reasons[:3])}）")
        return None

    async def _discover_upload_services(self) -> List[str]:
        """S72: 候选顺序表（disco 命中优先+惯例名），逐候选试到成功，不再一次失败定死。"""
        if self._upload_service_jid:
            return [self._upload_service_jid]
        items = []
        try:
            disco = await self.xmpp.plugin["xep_0030"].get_items(jid=self.domain, timeout=10)
            for it in disco.xml.findall(".//{%s}item" % DISCO_ITEMS_NS):
                items.append((it.get("jid"), it.get("name")))
        except Exception as e:
            logging.getLogger("app").info("XEP-0363 disco 发现失败（改用惯例名）: %r", e)
        return pick_upload_services(items, self.domain)

    async def _request_slot(self, service_jid: str, name: str, size: int):
        iq = self.xmpp.Iq(stype="get", sto=service_jid)
        iq.xml.append(build_slot_request(name, size))
        try:
            resp = await iq.send(timeout=15)
        except Exception as e:
            xml = getattr(getattr(e, "iq", None), "xml", None)
            kind = slot_error_kind(xml) if xml is not None else "error"
            logging.getLogger("app").info("XEP-0363 slot 请求失败(%s): %r", service_jid, e)
            return None, None, kind
        slot = resp.xml.find("{%s}slot" % UPLOAD_NS)
        if slot is None:
            return None, None, "noservice"
        put = slot.find("{%s}put" % UPLOAD_NS)
        get = slot.find("{%s}get" % UPLOAD_NS)
        return (put.get("url") if put is not None else None,
                get.get("url") if get is not None else None,
                None if put is not None else "noservice")

    def _send_sims(self, chat_jid: str, url: str, name: str, size: int, mime: str):
        # S75: slixmpp 1.17 StanzaBase 无 m*/b* kwargs 魔法（bto= 直接 TypeError，
        # 潜伏自 M5，S72 打通上传后首次暴露）——改显式属性赋值。
        # S76: 附件三件套与桥接同构（客户端只认 reference/media-sharing+oob），
        # body 置于附件元素之后（桥接实证的对现代客户端顺序模式）。
        msg = self.xmpp.Message()
        msg["to"] = chat_jid
        msg["type"] = "chat"
        for el in build_file_share(url, name, size, mime):
            msg.xml.append(el)
        msg["body"] = f"📎 {name}\n{url}"
        msg.send()
        logging.getLogger("app").info("[XMPP] 附件消息已发: %s → %s (%s)", name, chat_jid, url)

    # -------------------- 行为引擎（主动事件） --------------------
    async def execute_behavior_event(self, chat_jid: str, behavior_item: BehaviorItem):
        # S71：空 chat_jid（diary/behavior 引擎空目标语义）-> 展开已配置目标；仍空则告警跳过。
        if not chat_jid:
            targets = [t for t in (self.behaviorTargetJids or []) if t]
            if not targets:
                logging.getLogger("app").warning(
                    "[XMPP] 行为事件无目标 JID（未配置行为目标），跳过本次事件")
                return
            for t in dict.fromkeys(targets):
                await self.execute_behavior_event(t, behavior_item)
            return
        # S71：slixmpp 流绑定 bot 线程 loop，而行为/日记派发在 server 主 loop ->
        # 整个事件协程桥接回 bot loop 执行（run_coroutine_threadsafe，对齐 feishu 先例）。
        bot_loop = None
        ref = self._manager_ref() if self._manager_ref else None
        if ref is not None:
            bot_loop = getattr(ref, "loop", None)
        if bot_loop is not None and not bot_loop.is_closed():
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is not bot_loop:
                fut = asyncio.run_coroutine_threadsafe(
                    self._execute_behavior_event(chat_jid, behavior_item), bot_loop)
                await asyncio.wrap_future(fut)
                return
        await self._execute_behavior_event(chat_jid, behavior_item)

    @llm_gate.gated
    async def _execute_behavior_event(self, chat_jid: str, behavior_item: BehaviorItem):
        prompt_content = await self._resolve_behavior_prompt(behavior_item)
        if not prompt_content:
            return
        if chat_jid not in self.memoryList:
            self.memoryList[chat_jid] = await self._restore_conv(chat_jid)
        instruction = f"[system]: {prompt_content}"
        messages = self.memoryList[chat_jid].copy() + [{"role": "user", "content": instruction}]
        self.memoryList[chat_jid].append({"role": "user", "content": instruction})
        try:
            client = AsyncOpenAI(api_key="super-secret-key",
                                 base_url=f"http://127.0.0.1:{get_port()}/v1")
            resp = await client.chat.completions.create(
                model=self.XmppAgent, messages=messages, stream=False,
                extra_body={"is_app_bot": True, "platform": "xmpp",
                            "behavior_trigger": True,
                            **self._tools_override(),
                            **behavior_item.tools_override()})
            reply = (resp.choices[0].message.content or "").strip()
            if not reply:
                log_empty_reply("xmpp-behavior", chat_jid)
                return
            self.memoryList[chat_jid].append({"role": "assistant", "content": reply})
            await self._send_text(chat_jid, reply)
            await self._send_local_images(chat_jid, reply)
            await self._persist_conv(chat_jid)
        except Exception as e:
            logging.getLogger("app").error(f"XMPP 行为事件失败: {e}")

    async def _resolve_behavior_prompt(self, behavior_item: BehaviorItem) -> Optional[str]:
        try:
            content = getattr(behavior_item, "content", None)
            if content:
                return content
            prompt = getattr(getattr(behavior_item, "action", None), "prompt", None)
            return prompt or None
        except Exception:
            return None
