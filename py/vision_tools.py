# -*- coding: utf-8 -*-
"""S299：视觉工具与图片消息注入（自 server.py 逐字搬移）。

- 二手视觉：get_image_content / analyze_image / analyze_images / review_image（独立 VLM 转述）
- 一手视觉：view_images（像素直注本会话）
- 消息注入/剔图：images_in_messages / images_add_in_messages / message_without_images /
  _strip_image_parts_from_messages / _image_magic_ok / _attach_screen_image_for_behavior

server 全局（client/settings/PORT/current_request_messages）经函数内 py.srv_ref.srv() 取活实例（部署形态 server=__main__，禁 import server）
（routers 同款惯例）；server 侧保留原名 re-export。行为与搬移前逐字一致。
"""
import copy
import hashlib
import logging
import os
import re
from typing import Dict, List

from openai import AsyncOpenAI

from py.get_setting import UPLOAD_FILES_DIR, load_settings
from py.llm_recovery import acreate, llm_retry_cfg
from py.llm_tool import get_image_base64, get_image_media_type

logger = logging.getLogger("app")


# S299：server 侧小参数助手与请求上下文——保持运行期单一事实源，函数体保持原样，
# 经包装惰性取 server 模块属性（server 已完成导入后才会被调用，无环）。
def _main_param(*a, **k):
    from py.srv_ref import srv as _srv
    return _srv()._main_param(*a, **k)


def _role_param(*a, **k):
    from py.srv_ref import srv as _srv
    return _srv()._role_param(*a, **k)


def _append_note(*a, **k):
    from py.srv_ref import srv as _srv
    return _srv()._append_note(*a, **k)


async def get_image_content(image_url: str) -> str:
    import hashlib
    settings = await load_settings()
    base64_image = await get_image_base64(image_url)
    media_type = await get_image_media_type(image_url, base64_image)
    url= f"data:{media_type};base64,{base64_image}"
    image_hash = hashlib.md5(image_url.encode()).hexdigest()
    content = ""
    if settings['vision']['enabled'] and not settings.get('unifiedModel'):
        # 如果uploaded_files/{item['image_url']['hash']}.txt存在，则读取文件内容，否则调用vision api
        if os.path.exists(os.path.join(UPLOAD_FILES_DIR, f"{image_hash}.txt")):
            with open(os.path.join(UPLOAD_FILES_DIR, f"{image_hash}.txt"), "r", encoding='utf-8') as f:
                content += f"\n\n图片(URL:{image_url} 哈希值：{image_hash})信息如下：\n\n"+str(f.read())+"\n\n"
        else:
            images_content = [{"type": "text", "text": "请仔细描述图片中的内容，包含图片中可能存在的文字、数字、颜色、形状、大小、位置、人物、物体、场景等信息。"},{"type": "image_url", "image_url": {"url": url}}]
            client = AsyncOpenAI(api_key=settings['vision']['api_key'],base_url=settings['vision']['base_url'])
            
            extra = {}

            if _role_param(settings, 'vision', 'temperature') !=1:
                extra['temperature'] = _role_param(settings, 'vision', 'temperature')
            
            response = await acreate(
                lambda: client.chat.completions.create(
                model=settings['vision']['model'],
                messages = [{"role": "user", "content": images_content}],
                **extra
            ), attempts=2, base_delay=1.0, label="s207-get_image_content")
            content = f"\n\n图片(URL:{image_url} 哈希值：{image_hash})信息如下：\n\n"+str(response.choices[0].message.content)+"\n\n"
            with open(os.path.join(UPLOAD_FILES_DIR, f"{image_hash}.txt"), "w", encoding='utf-8') as f:
                f.write(str(response.choices[0].message.content))
    else:           
        # 如果uploaded_files/{item['image_url']['hash']}.txt存在，则读取文件内容，否则调用vision api
        if os.path.exists(os.path.join(UPLOAD_FILES_DIR, f"{image_hash}.txt")):
            with open(os.path.join(UPLOAD_FILES_DIR, f"{image_hash}.txt"), "r", encoding='utf-8') as f:
                content += f"\n\n图片(URL:{image_url} 哈希值：{image_hash})信息如下：\n\n"+str(f.read())+"\n\n"
        else:
            images_content = [{"type": "text", "text": "请仔细描述图片中的内容，包含图片中可能存在的文字、数字、颜色、形状、大小、位置、人物、物体、场景等信息。"},{"type": "image_url", "image_url": {"url": url}}]
            client = AsyncOpenAI(api_key=settings['api_key'],base_url=settings['base_url'])
            
            extra = {}

            if _main_param(settings, 'temperature') != 1:
                extra['temperature'] = _main_param(settings, 'temperature')
            
            response = await acreate(
                lambda: client.chat.completions.create(
                model=settings['model'],
                messages = [{"role": "user", "content": images_content}],
                **extra
            ), attempts=2, base_delay=1.0, label="s207-get_image_content")
            content = f"\n\n图片(URL:{image_url} 哈希值：{image_hash})信息如下：\n\n"+str(response.choices[0].message.content)+"\n\n"
            with open(os.path.join(UPLOAD_FILES_DIR, f"{image_hash}.txt"), "w", encoding='utf-8') as f:
                f.write(str(response.choices[0].message.content))
    return content

async def analyze_image(image_url: str, prompt: str) -> str:
    """针对特定提示词分析图像，不使用通用描述缓存"""
    settings = await load_settings()
    base64_image = await get_image_base64(image_url)
    media_type = await get_image_media_type(image_url, base64_image)
    url = f"data:{media_type};base64,{base64_image}"
    
    if settings['vision']['enabled'] and not settings.get('unifiedModel'):
        client = AsyncOpenAI(api_key=settings['vision']['api_key'], base_url=settings['vision']['base_url'])
        extra = {}
        if _role_param(settings, 'vision', 'temperature') != 1:
            extra['temperature'] = _role_param(settings, 'vision', 'temperature')
        
        response = await acreate(
            lambda: client.chat.completions.create(
            model=settings['vision']['model'],
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": url}}]}],
            **extra
        ), attempts=2, base_delay=1.0, label="s207-secondhand_describe_image")
        return response.choices[0].message.content
    else:
        client = AsyncOpenAI(api_key=settings['api_key'], base_url=settings['base_url'])
        extra = {}
        if _main_param(settings, 'temperature') != 1:
            extra['temperature'] = _main_param(settings, 'temperature')
        response = await acreate(
            lambda: client.chat.completions.create(
            model=settings['model'],
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": url}}]}],
            **extra
        ), attempts=2, base_delay=1.0, label="s207-secondhand_describe_image")
        return response.choices[0].message.content

async def analyze_images(image_urls: list, prompt: str) -> str:
    """一次性将多张图片交给VLM联合分析或比较，每张图前附序号标记便于模型指代"""
    settings = await load_settings()
    if not image_urls:
        return "错误：image_urls 不能为空"
    content = [{"type": "text", "text": prompt}]
    for index, image_url in enumerate(image_urls, start=1):
        base64_image = await get_image_base64(image_url)
        media_type = await get_image_media_type(image_url, base64_image)
        content.append({"type": "text", "text": f"【第{index}张图】"})
        content.append({"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{base64_image}"}})

    if settings['vision']['enabled'] and not settings.get('unifiedModel'):
        client = AsyncOpenAI(api_key=settings['vision']['api_key'], base_url=settings['vision']['base_url'])
        extra = {}
        if _role_param(settings, 'vision', 'temperature') != 1:
            extra['temperature'] = _role_param(settings, 'vision', 'temperature')
        response = await acreate(
            lambda: client.chat.completions.create(
            model=settings['vision']['model'],
            messages=[{"role": "user", "content": content}],
            **extra
        ), attempts=2, base_delay=1.0, label="s207-secondhand_describe_images")
        return response.choices[0].message.content
    else:
        client = AsyncOpenAI(api_key=settings['api_key'], base_url=settings['base_url'])
        extra = {}
        if _main_param(settings, 'temperature') != 1:
            extra['temperature'] = _main_param(settings, 'temperature')
        response = await acreate(
            lambda: client.chat.completions.create(
            model=settings['model'],
            messages=[{"role": "user", "content": content}],
            **extra
        ), attempts=2, base_delay=1.0, label="s207-secondhand_describe_images")
        return response.choices[0].message.content

def _image_magic_ok(head: bytes) -> bool:
    """S252: 图像字节魔数判定（PNG/JPEG/GIF/WebP/BMP）。head 建议取前 16 字节。"""
    if not head or len(head) < 8:
        return False
    if head[:4] == b"\x89PNG":
        return True
    if head[:3] == b"\xff\xd8\xff":
        return True
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return True
    if head[:4] == b"GIF8":
        return True
    if head[:2] == b"BM":
        return True
    return False

def _strip_image_parts_from_messages(msg_list) -> int:
    """S252: 剥离请求体中全部图像/视频 parts（引擎加载图像失败 400 后的降级重试用）。
    返回剥离条数；含图消息保留文本+注记。"""
    removed = 0
    if not isinstance(msg_list, list):
        return 0
    for m in msg_list:
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, list):
            keep = [p for p in c if not (isinstance(p, dict) and p.get("type") in ("image_url", "video_url"))]
            n = len(c) - len(keep)
            if n:
                removed += n
                note = {"type": "text", "text": "[image stripped] 引擎无法加载本轮图像（已自动剥离图像降级为文本重试，可能因伪装/不支持的图像字节）"}
                m["content"] = keep + [note]
    return removed

async def view_images(image_urls: list) -> str:
    """S243 一手视觉：不调任何VLM。登记/校验图片后返回 URL 列表文本，
    实际像素由 _maybe_inject_browser_vision 管线（view_images 已入
    _BROWSER_VISION_TOOLS）注入后续模型调用，主模型亲自看图（同附图消息路径）。"""
    from py.load_files import ALLOWED_IMAGE_EXTENSIONS
    import shutil
    import hashlib as _hashlib
    from urllib.parse import unquote as _unquote, urlparse as _urlparse
    from py.get_setting import get_host, get_port
    _gh, _gp = get_host(), get_port()
    if not image_urls or not isinstance(image_urls, list):
        return "错误：image_urls 不能为空"
    max_n = 3
    urls = []
    errs = []
    for one in image_urls:
        one = (one or "").strip()
        if not one:
            continue
        if len(urls) >= max_n:
            errs.append("单次最多附上前3张，多余的已忽略")
            break
        try:
            parsed = _urlparse(one)
            if parsed.scheme == "file":
                # S259: file:///C:/x.png 这类应能用——解析成本地路径走既有登记通道
                from urllib.request import url2pathname
                _fp = url2pathname(parsed.path or "")
                if parsed.netloc and parsed.netloc not in ("", "localhost"):
                    _fp = "\\\\" + parsed.netloc + _fp
                if _fp:
                    one = _fp
                    parsed = _urlparse(one)
            if parsed.scheme in ("blob", "javascript", "about", "mailto", "ws", "wss"):
                # S259: blob: 只在页面内存有效（take_snapshot 的懒加载图可能是 blob 渲染）——
                # 外站/后端永远取不到，专错直导像素路，别让 agent 误当文件/魔数问题瞎试
                errs.append(f"{one[:90]}: {parsed.scheme}: URL 只存在于页面内存（或非资源协议），外部无法获取"
                            "——看该图渲染像素用 take_screenshot(uid)（元素截图不走 URL）；"
                            "要可下载的地址就 take_snapshot 找它的 http(s) 源")
                continue
            if parsed.scheme in ("http", "https"):
                if ('uploaded_files' in parsed.path or 'tool_temp' in parsed.path) and (
                        parsed.hostname in ("127.0.0.1", "localhost", "0.0.0.0", _gh) or not parsed.hostname):
                    fname = os.path.basename(_unquote(parsed.path))
                    fpath = os.path.join(UPLOAD_FILES_DIR, fname)
                    if not os.path.isfile(fpath) or os.path.getsize(fpath) == 0:
                        errs.append(f"{one}: 内部图片不存在或为0字节")
                        continue
                    _ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
                    if _ext not in ALLOWED_IMAGE_EXTENSIONS:
                        errs.append(f"{one}: 非图片格式({_ext or '无扩展名'})")
                        continue
                    # S252: 扩展名合法≠字节合法（历史污染：HTML 伪装 .png 落盘）——查文件头魔数
                    try:
                        with open(fpath, "rb") as _ff:
                            _hdr = _ff.read(16)
                    except OSError:
                        _hdr = b""
                    if not _image_magic_ok(_hdr):
                        errs.append(f"{one}: 内部文件首字节非图片魔数（疑似 HTML/防盗链页伪装的污染文件），建议删除后重新获取")
                        continue
                    urls.append(one)
                else:
                    # 公网/其它 URL：预读并落盘为内部 URL（S245：不透传外链——注入端
                    # 二次下载可能瞬败，且本地推理服务器不会拉远程图，裸 http url 必 400）
                    b64 = await get_image_base64(one)
                    if not b64:
                        errs.append(f"{one}: 图片读取失败或为空")
                        continue
                    import base64 as _b64m
                    raw = _b64m.b64decode(b64)
                    # S252: 严格魔数——不用 get_image_media_type（其嗅探失败会按 URL 后缀猜、
                    # 猜不中还默认 image/png，把 200+HTML 的防盗链页当 png 落盘 → 注入后引擎
                    # 400 "Failed to load image" 炸整轮；22:22 贴吧签名图事故实证）
                    from py.llm_tool import sniff_media_type_from_base64
                    _mt = sniff_media_type_from_base64(b64)
                    _ext2 = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif",
                             "image/webp": "webp", "image/bmp": "bmp"}.get(_mt, "")
                    if not raw or not _ext2:
                        _head = (raw[:40].decode("utf-8", "replace") if raw else "")
                        errs.append(f"{one}: 下载内容非有效图片字节（未识别魔数:{_mt or '无'}；防盗链/反爬页常见）。首字节: {_head!r}。"
                                    "提示：防盗链站（如贴吧图片）请用 new_page 打开原页面后 take_screenshot 查看，或换图片来源")
                        continue
                    os.makedirs(UPLOAD_FILES_DIR, exist_ok=True)
                    unique = "view_" + _hashlib.md5(raw).hexdigest()[:16] + "." + _ext2
                    dest = os.path.join(UPLOAD_FILES_DIR, unique)
                    if not os.path.isfile(dest):
                        with open(dest, "wb") as _f:
                            _f.write(raw)
                    urls.append(f"http://{_gh}:{_gp}/uploaded_files/{unique}")
            else:
                # 本机本地路径：存在+扩展名校验后复制进 uploaded_files 生成内部 URL
                p = os.path.abspath(os.path.expanduser(one))
                if not os.path.isfile(p) or os.path.getsize(p) == 0:
                    errs.append(f"{one}: 文件不存在或为0字节")
                    continue
                _ext = p.rsplit('.', 1)[-1].lower() if '.' in os.path.basename(p) else ''
                if _ext not in ALLOWED_IMAGE_EXTENSIONS:
                    errs.append(f"{one}: 非图片格式({_ext or '无扩展名'})")
                    continue
                os.makedirs(UPLOAD_FILES_DIR, exist_ok=True)
                _sig = _hashlib.md5(f"{p}|{os.path.getsize(p)}|{int(os.path.getmtime(p))}".encode()).hexdigest()[:16]
                unique = f"view_{_sig}.{_ext}"
                dest = os.path.join(UPLOAD_FILES_DIR, unique)
                if not os.path.isfile(dest):
                    shutil.copy2(p, dest)
                urls.append(f"http://{_gh}:{_gp}/uploaded_files/{unique}")
        except Exception as e:
            errs.append(f"{one}: {e!r}")
    if not urls:
        return "错误：没有可附上的图片。" + "；".join(errs) if errs else "错误：没有可附上的图片"
    tail = f"（FIRST-HAND：图像将随本轮对话直接附上，请据图亲自判断并作答，无需再调用任何 secondhand_* 转述工具。）"
    out = f"Images attached for direct viewing: {' '.join(urls)}\n{tail}"
    if errs:
        out += "\n(部分图片未能附上: " + "；".join(errs) + ")"
    return out

async def review_image(image_url: str, prompt: str) -> str:
    """基于对话上下文审查图像，使VLM像读连环画一样理解图像在对话中的位置和意义
    
    截断行为由 vision.contextTruncation 配置控制：
    - False（默认）：完整传递对话历史，不做任何截断。适用于本地部署等不在意token数的场景。
    - True：启用截断以节省token。会剥离思考内容，限制历史条数，截断过长消息。
    """
    settings = await load_settings()
    base64_image = await get_image_base64(image_url)
    media_type = await get_image_media_type(image_url, base64_image)
    url = f"data:{media_type};base64,{base64_image}"
    
    # 读取截断配置，默认不截断（完整传递上下文，审查质量最高）
    vision_cfg = settings.get('vision', {})
    context_truncation = vision_cfg.get('contextTruncation', False)
    
    # 从 contextvars 获取当前对话历史（S299：ContextVar 本体在 server 模块，
    # 经模块属性运行期取——同一 var 实例 .set()/.get() 配对语义不变）
    from py.srv_ref import srv as _srv
    raw_messages = _srv().current_request_messages.get() or []
    
    # 构建上下文消息：只保留文本，去除图片以节省token
    context_messages = [
        {"role": "system", "content": "你是一个图像审查助手。你需要基于对话上下文来审查图像是否符合要求。以下是之前的对话历史，请结合上下文理解当前图像的意义："}
    ]
    
    if context_truncation:
        # ===== 截断模式：节省token，适合云端API =====
        # 限制历史长度
        recent_messages = raw_messages[-20:] if len(raw_messages) > 20 else raw_messages
        for msg in recent_messages:
            content = msg.get('content', '')
            role = msg.get('role', '')
            if role not in ('user', 'assistant'):
                continue
            # 如果content是list（图文混合），只提取文本部分
            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get('type') == 'text':
                        text_parts.append(item.get('text', ''))
                content = '\n'.join(text_parts)
            if content and isinstance(content, str) and content.strip():
                # 剥离思考内容（深度思考模式下，思考过程可能很长但审查图像通常不需要看AI的内心独白）
                # 匹配 <think>...</think> 或 ༞...༎ 或 <thought>...</thought> 等常见思考标签
                content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
                content = re.sub(r'༎.*?༎', '', content, flags=re.DOTALL)
                content = re.sub(r'<thought>.*?</thought>', '', content, flags=re.DOTALL)
                content = content.strip()
                # 截断过长的单条消息
                if len(content) > 500:
                    content = content[:500] + "...(已截断)"
                if content:
                    context_messages.append({"role": role, "content": content})
    else:
        # ===== 完整模式（默认）：不截断，完整传递上下文 =====
        # 适用于本地部署等不在意token数的场景，审查质量最高
        for msg in raw_messages:
            content = msg.get('content', '')
            role = msg.get('role', '')
            if role not in ('user', 'assistant'):
                continue
            # 如果content是list（图文混合），只提取文本部分（图片已单独传给VLM，无需重复）
            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get('type') == 'text':
                        text_parts.append(item.get('text', ''))
                content = '\n'.join(text_parts)
            if content and isinstance(content, str) and content.strip():
                context_messages.append({"role": role, "content": content})
    
    # 添加实际的审查请求（带图片）
    context_messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": url}}
        ]
    })
    
    # 调用VLM
    if settings['vision']['enabled'] and not settings.get('unifiedModel'):
        client = AsyncOpenAI(api_key=settings['vision']['api_key'], base_url=settings['vision']['base_url'])
        extra = {}
        if _role_param(settings, 'vision', 'temperature') != 1:
            extra['temperature'] = _role_param(settings, 'vision', 'temperature')
        response = await acreate(
            lambda: client.chat.completions.create(
            model=settings['vision']['model'],
            messages=context_messages,
            **extra
        ), attempts=2, base_delay=1.0, label="s207-secondhand_review_image")
        return response.choices[0].message.content
    else:
        client = AsyncOpenAI(api_key=settings['api_key'], base_url=settings['base_url'])
        extra = {}
        if _main_param(settings, 'temperature') != 1:
            extra['temperature'] = _main_param(settings, 'temperature')
        response = await acreate(
            lambda: client.chat.completions.create(
            model=settings['model'],
            messages=context_messages,
            **extra
        ), attempts=2, base_delay=1.0, label="s207-secondhand_review_image")
        return response.choices[0].message.content

async def message_without_images(messages: List[Dict]) -> List[Dict]:
    if messages:
        for message in messages:
            if 'content' in message:
                if isinstance(message['content'], list):
                    for item in message['content']:
                        # 剥离包含图像和视频的内容，只保留文本传递（用于快速生成请求或剥离富媒体阶段）
                        if isinstance(item, dict) and item.get('type') == 'text':
                            message['content'] = item['text']
                            break
    return messages

async def images_in_messages(messages: List[Dict], fastapi_base_url: str) -> List[Dict]:
    from py.srv_ref import srv as _srv  # S299：PORT 事实源在 server（启动竞态落定后的最终值）
    media_items = []
    index = 0
    for message in messages:
        extracted_media =[]
        if 'content' in message:
            if isinstance(message['content'], list):
                for item in message['content']:
                    # 动态捕获图片或视频
                    if isinstance(item, dict) and item.get('type') in ['image_url', 'video_url']:
                        media_key = item['type']  # 'image_url' 或 'video_url'
                        
                        if item[media_key]["url"].startswith("http"):
                            media_url = item[media_key]["url"]
                            if fastapi_base_url in media_url:
                                media_url = media_url.replace(fastapi_base_url, f"http://127.0.0.1:{_srv().PORT}/")
                            
                            # 假设你的 get_image_base64 同样可以将视频流转为 Base64
                            base64_data = await get_image_base64(media_url)
                            # 假设 get_image_media_type 也能正常返回 video/mp4, video/webm 等
                            mime_type = await get_image_media_type(media_url, base64_data)

                            # S264: 本地推理服务器解码器不认 webp/avif 等格式（400 炸整轮实证），
                            # 白名单外统一转码 JPEG。主流程与 browser_vision 注入共用本函数=单点全覆盖。
                            if media_key == 'image_url':
                                from py.llm_tool import _normalize_image_for_server
                                base64_data, mime_type = _normalize_image_for_server(base64_data, mime_type)

                            item[media_key]["url"] = f"data:{mime_type};base64,{base64_data}"
                            item[media_key]["hash"] = hashlib.md5(item[media_key]["url"].encode()).hexdigest()
                        else:
                            item[media_key]["hash"] = hashlib.md5(item[media_key]["url"].encode()).hexdigest()

                        extracted_media.append(item)
        if extracted_media:
            # 保持原来的字典结构向下兼容，images 实际上装载了 media
            media_items.append({'index': index, 'images': extracted_media})
        index += 1
    return media_items

async def images_add_in_messages(request_messages: List[Dict], images: List[Dict], settings: dict) -> List[Dict]:
    messages = copy.deepcopy(request_messages)
    
    if settings['vision']['enabled'] and not settings.get('unifiedModel'):
        for image in images:
            index = image['index']
            if index < len(messages):
                if 'content' in messages[index]:
                    for item in image['images']:
                        media_key = item['type']  # 'image_url' 或 'video_url'
                        file_hash = item[media_key]['hash']
                        media_name = "视频" if media_key == "video_url" else "图片"
                        
                        # 统一缓存处理，如果是视频就是视频文本解析记录
                        cache_file = os.path.join(UPLOAD_FILES_DIR, f"{file_hash}.txt")
                        if os.path.exists(cache_file):
                            with open(cache_file, "r", encoding='utf-8') as f:
                                messages[index]['content'] = _append_note(
                                    messages[index]['content'],
                                    f"\n\nsystem: 用户发送的{media_name}(哈希值：{file_hash})信息如下：\n\n{f.read()}\n\n")
                        else:
                            # 根据输入类型调整提示词
                            prompt_text = "请仔细描述这段视频中的内容，包含视频中发生的事件、场景变化、人物动作以及关键细节等信息。" if media_key == "video_url" else "请仔细描述图片中的内容，包含图片中可能存在的文字、数字、颜色、形状、大小、位置、人物、物体、场景等信息。"
                            
                            media_content =[
                                {"type": "text", "text": prompt_text},
                                {"type": media_key, media_key: {"url": item[media_key]['url']}}
                            ]
                            
                            # 直接交给视觉模型（视觉模型需原生支持视频）
                            client = AsyncOpenAI(api_key=settings['vision']['api_key'], base_url=settings['vision']['base_url'])
                            
                            extra = {}

                            if _role_param(settings, 'vision', 'temperature') !=1:
                                extra['temperature'] = _role_param(settings, 'vision', 'temperature')

                            response = await acreate(
                                lambda: client.chat.completions.create(
                                model=settings['vision']['model'],
                                messages=[{"role": "user", "content": media_content}],
                                **extra
                            ), attempts=llm_retry_cfg(settings)[0], base_delay=llm_retry_cfg(settings)[1], label="s207-images_add_in_messages")
                            result_text = str(response.choices[0].message.content)
                            messages[index]['content'] = _append_note(
                                messages[index]['content'],
                                f"\n\nsystem: 用户发送的{media_name}(哈希值：{file_hash})信息如下：\n\n{result_text}\n\n")
                            
                            with open(cache_file, "w", encoding='utf-8') as f:
                                f.write(result_text)
    else:           
        for image in images:
            index = image['index']
            if index < len(messages):
                if 'content' in messages[index]:
                    for item in image['images']:
                        media_key = item['type']  # 'image_url' 或 'video_url'
                        file_hash = item[media_key]['hash']
                        media_name = "视频" if media_key == "video_url" else "图片"
                        
                        cache_file = os.path.join(UPLOAD_FILES_DIR, f"{file_hash}.txt")
                        if os.path.exists(cache_file):
                            with open(cache_file, "r", encoding='utf-8') as f:
                                messages[index]['content'] = _append_note(
                                    messages[index]['content'],
                                    f"\n\nsystem: 用户发送的{media_name}(哈希值：{file_hash})信息如下：\n\n{f.read()}\n\n")
                        else:
                            if isinstance(messages[index]['content'], str):
                                messages[index]['content'] =[{"type": "text", "text": messages[index]['content']}]
                            
                            # 未开启视觉模型，直接以原生的 `video_url` 或 `image_url` 拼入请求，让当前大模型自行读取理解
                            messages[index]['content'].append({"type": media_key, media_key: {"url": item[media_key]['url']}})
                            
    return messages

def _attach_screen_image_for_behavior(msg: List[Dict], request, settings: dict) -> None:
    """S225：旁观发言附截图。unifiedModel 开启 + 行为轮 + 带 screen_image 时，把观察帧以原生
    image_url 注入本次发言**生成调用**的消息。msg 为 images_add_in_messages 的 deepcopy，只改它
    → 主模型原生读图（一手），不触碰 request.messages，故截图不入 mem0(user_prompt)/turn-log
    (request.messages)/DB/输出消息。仅 unified 生效：非 unified=独立视觉二手，按设计不附图。"""
    if not getattr(request, "behavior_trigger", False):
        return
    b64 = (getattr(request, "screen_image", "") or "").strip()
    if not b64 or not (settings or {}).get("unifiedModel"):
        return
    if not msg:
        return
    last = msg[-1]
    text = last.get("content")
    if isinstance(text, str):
        last["content"] = [{"type": "text", "text": text}]
    if isinstance(last.get("content"), list):
        last["content"].append(
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
