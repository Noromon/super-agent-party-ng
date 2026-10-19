# -*- coding: utf-8 -*-
"""M5-XMPP 第九 bot 通道（收编 xmpp-bridge 扩展，直连 /v1 agent 内核）。

家族结构照搬 TelegramClient：memoryList + AsyncOpenAI 自调用本机 /v1
（asyncToolsID/fileLinks/is_app_bot 契约）+ 分隔符分段发送。
XMPP 侧：slixmpp（TCP 5222 / TLS 5223；wss 传输不支持并给出明确报错）、
XEP-0066 OOB 与内联 base64 收图、XEP-0363 HTTP Upload + SIMS 发图。
安全：外发本地图片仅限 UPLOAD_FILES_DIR / TOOL_TEMP_DIR / KB_DIR 围栏内；
扩展的 local-image?path= 任意文件读 fallback 已废除（上传失败只发文字）。
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
from py.get_setting import (KB_DIR, TOOL_TEMP_DIR, UPLOAD_FILES_DIR,
                            get_port, load_settings)

UPLOAD_NS = "urn:xmpp:http:upload:0"
SIMS_NS = "urn:xmpp:sims:1"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")


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
        self.config = None
        self._is_ready = False
        self._manager_ref = None
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
            connector=aiohttp.TCPConnector(ssl=False))

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
            await self._send_text(frm, "对话记录已重置，开始新话题吧！")
            return
        if text.lower() == "/id":
            await self._send_text(frm, f"当前 JID（用于自主行为目标列表）:\n{frm}")
            return
        if text.lower() == "/help":
            await self._send_text(frm, "/new 清空对话  /id 查看目标ID  /help 帮助")
            return
        if self.wakeWord and self.wakeWord not in text:
            return

        images = self._extract_incoming_images(msg, text)
        if images:
            content = [{"type": "image_url", "image_url": {"url": uri}} for uri in images]
            content.append({"type": "text", "text": text or "用户发送了一张图片"})
            await self._process_llm(frm, "", content)
        else:
            await self._process_llm(frm, text, [])

    def _extract_incoming_images(self, msg, text) -> List[str]:
        uris: List[str] = []
        try:  # XEP-0066 OOB
            oob = msg.get("oob", None)
            if oob is not None:
                for url in oob.get("urls", []) or []:
                    if isinstance(url, str) and url.lower().startswith(("http://", "https://")):
                        uris.append(url)
        except Exception:
            pass
        for m in re.finditer(r"data:image/(\w+);base64,([A-Za-z0-9+/=]{200,})", text):
            uris.append(m.group(0))
        return uris[:4]

    # -------------------- LLM 内核（/v1 自调用，全 agent 能力） --------------------
    async def _process_llm(self, chat_jid: str, text: str, extra_content: List[dict]):
        self.memoryList.setdefault(chat_jid, [])
        self.asyncToolsID.setdefault(chat_jid, [])
        self.fileLinks.setdefault(chat_jid, [])
        user_msg = {"role": "user", "content": extra_content or text}
        self.memoryList[chat_jid].append(user_msg)

        settings = await load_settings()
        client = AsyncOpenAI(api_key="super-secret-key",
                             base_url=f"http://127.0.0.1:{get_port()}/v1")
        out_buffer = ""
        full_text = []
        try:
            stream = await client.chat.completions.create(
                model=self.XmppAgent,
                messages=self.memoryList[chat_jid],
                stream=True,
                extra_body={
                    "asyncToolsID": self.asyncToolsID[chat_jid],
                    "fileLinks": self.fileLinks[chat_jid],
                    "is_app_bot": True,
                    "platform": "xmpp",
                },
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", "") or ""
                reasoning = getattr(delta, "reasoning_content", "") or ""
                tool_link = getattr(delta, "tool_link", "") or ""
                async_tool_id = getattr(delta, "async_tool_id", "") or ""
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
        self.memoryList[chat_jid].append({"role": "assistant", "content": assistant_text})
        if self.memoryLimit > 0:
            while len(self.memoryList[chat_jid]) > self.memoryLimit * 2:
                self.memoryList[chat_jid].pop(0)
                if self.memoryList[chat_jid]:
                    self.memoryList[chat_jid].pop(0)

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
            logging.error(f"XMPP 发送失败: {e}")

    def _fence_ok(self, path: str) -> bool:
        return path_under(path, [UPLOAD_FILES_DIR, TOOL_TEMP_DIR, KB_DIR])

    async def _send_local_images(self, chat_jid: str, full_text: str):
        for m in re.finditer(r"([A-Za-z]:[\\/][^\s|\"'<>\[\]]+|/[^\s|\"'<>\[\]]+)"
                             r"(" + "|".join(re.escape(e) for e in IMAGE_EXTS) + r")",
                             full_text, re.IGNORECASE):
            raw = m.group(0)
            if not self._fence_ok(raw):
                logging.warning("XMPP 拒绝外发围栏外路径: %s", raw)
                continue
            if not os.path.isfile(raw):
                continue
            if not self._xep0363_supported:
                await self._send_text(chat_jid, f"（图片暂无法上传：{os.path.basename(raw)}）")
                continue
            try:
                url = await self._upload_and_share(chat_jid, raw)
                if not url:
                    await self._send_text(chat_jid, f"（图片上传失败：{os.path.basename(raw)}）")
            except Exception as e:
                logging.error(f"XMPP 图片外发失败: {e}")
                await self._send_text(chat_jid, f"（图片上传失败：{os.path.basename(raw)}）")

    async def _upload_and_share(self, chat_jid: str, file_path: str) -> Optional[str]:
        size = os.path.getsize(file_path)
        name = os.path.basename(file_path)
        mime = "image/" + name.rsplit(".", 1)[-1].lower().replace("jpg", "jpeg")
        service = await self._discover_upload_service()
        if not service:
            self._xep0363_supported = False
            return None
        put_url, get_url = await self._request_slot(service, name, size)
        if not put_url:
            return None
        with open(file_path, "rb") as f:
            data = f.read()
        async with self.session.put(put_url, data=data,
                                    ssl=self._aio_ssl(put_url),
                                    headers={"Content-Type": "application/octet-stream"}) as resp:
            if resp.status not in (200, 201):
                return None
        self._send_sims(chat_jid, get_url, name, size, mime)
        return get_url

    async def _discover_upload_service(self) -> Optional[str]:
        if self._upload_service_jid:
            return self._upload_service_jid
        candidates = [f"httpfileupload.{self.domain}", f"upload.{self.domain}"]
        try:
            disco = await self.xmpp["xep_0030"].get_items(jid=self.domain, timeout=10)
            for item in disco["iter"]["items"]:
                nm = (item.get("name") or "").lower()
                jid = (item.get("jid") or "").lower()
                if "upload" in nm or "upload" in jid:
                    self._upload_service_jid = str(item.get("jid"))
                    return self._upload_service_jid
        except Exception as e:
            logging.debug(f"XEP-0363 disco 发现失败: {e}")
        for c in candidates:
            self._upload_service_jid = c
            return c
        return None

    async def _request_slot(self, service_jid: str, name: str, size: int):
        iq = self.xmpp.Iq(stype="get", sto=service_jid)
        req = ET.Element("{%s}request" % UPLOAD_NS)
        ET.SubElement(req, "filename", {"name": name}).text = name
        ET.SubElement(req, "size", {}).text = str(size)
        iq.xml.append(req)
        try:
            resp = await iq.send(timeout=15)
        except Exception as e:
            logging.warning(f"XEP-0363 slot 请求失败: {e}")
            self._xep0363_supported = False
            return None, None
        slot = resp.xml.find("{%s}slot" % UPLOAD_NS)
        if slot is None:
            self._xep0363_supported = False
            return None, None
        put = slot.find("{%s}put" % UPLOAD_NS)
        get = slot.find("{%s}get" % UPLOAD_NS)
        return (put.get("url") if put is not None else None,
                get.get("url") if get is not None else None)

    def _send_sims(self, chat_jid: str, url: str, name: str, size: int, mime: str):
        msg = self.xmpp.Message(bto=chat_jid, mtype="chat")
        msg["body"] = f"📎 {name}"
        sims = ET.Element("{%s}share" % SIMS_NS)
        preview = ET.SubElement(sims, "preview")
        ref = ET.SubElement(preview, "{urn:xmpp:reference:0}reference",
                            {"type": "content", "uri": url})
        ref.text = name
        media = ET.SubElement(preview, "{urn:xmpp:oob:1}oob")
        ET.SubElement(media, "url").text = url
        msg.xml.append(sims)
        msg.send()

    # -------------------- 行为引擎（主动事件） --------------------
    async def execute_behavior_event(self, chat_jid: str, behavior_item: BehaviorItem):
        prompt_content = await self._resolve_behavior_prompt(behavior_item)
        if not prompt_content:
            return
        self.memoryList.setdefault(chat_jid, [])
        instruction = f"[system]: {prompt_content}"
        messages = self.memoryList[chat_jid].copy() + [{"role": "user", "content": instruction}]
        self.memoryList[chat_jid].append({"role": "user", "content": instruction})
        try:
            client = AsyncOpenAI(api_key="super-secret-key",
                                 base_url=f"http://127.0.0.1:{get_port()}/v1")
            resp = await client.chat.completions.create(
                model=self.XmppAgent, messages=messages, stream=False,
                extra_body={"is_app_bot": True, "platform": "xmpp"})
            reply = (resp.choices[0].message.content or "").strip()
            if reply:
                self.memoryList[chat_jid].append({"role": "assistant", "content": reply})
                await self._send_text(chat_jid, reply)
                await self._send_local_images(chat_jid, reply)
        except Exception as e:
            logging.error(f"XMPP 行为事件失败: {e}")

    async def _resolve_behavior_prompt(self, behavior_item: BehaviorItem) -> Optional[str]:
        try:
            content = getattr(behavior_item, "content", None)
            if content:
                return content
            prompt = getattr(getattr(behavior_item, "action", None), "prompt", None)
            return prompt or None
        except Exception:
            return None
