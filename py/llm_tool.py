
import logging
import os
import base64
import json
import asyncio
import aiohttp
from urllib.parse import urlparse
from py.get_setting import load_settings, get_host, get_port # 确保导入了这两个函数
from openai import AsyncOpenAI

from py.load_files import check_robots_txt, is_private_ip, sanitize_url, ssrf_gate, NET_BLOCK_HINT, _make_session
from py import llm_gate

# ================= 安全配置 =================

# 建议包含项目地址，方便站长识别
USER_AGENT = "Mozilla/5.0 (compatible; OpenSourceImageBot/1.0)"
ROBOTS_CACHE = {}

# ================= 核心功能修改 =================

async def get_image_base64(image_url: str) -> str:
    """
    下载图片并转换为base64编码
    - 本地：支持直接读取本地磁盘路径文件（S153：file://、~、工作区相对路径归一；
      像路径但不存在→清晰报错，不再掉进 URL 抓取分支产生误导性失败。
      本地盘访问的授权在 dispatch 层路径门完成，本函数只管读取）
    - 对内：仅允许 'uploaded_files' 路径并重定向至本地
    - 对外：遵守 robots.txt 并拦截内网 IP (放行 Fake-IP)
    """
    from py.path_scope import normalize_path
    try:
        _st0 = await load_settings()
        _cwd = (_st0.get("CLISettings") or {}).get("cc_path") or os.getcwd()
    except Exception:
        _cwd = os.getcwd()
    info = normalize_path(image_url, _cwd)
    if info["kind"] == "path":
        if not info["exists"]:
            raise RuntimeError(f"本地文件不存在: {image_url}")
        try:
            with open(info["resolved"], 'rb') as f:
                image_data = f.read()
                return base64.b64encode(image_data).decode('utf-8')
        except Exception as e:
            raise RuntimeError(f"读取本地图片失败: {str(e)}")

    # 首先检查是否为存在的本地文件路径（kind=none 但真实存在的兜底，历史行为）
    if os.path.exists(image_url):
        try:
            with open(image_url, 'rb') as f:
                image_data = f.read()
                return base64.b64encode(image_data).decode('utf-8')
        except Exception as e:
            raise RuntimeError(f"读取本地图片失败: {str(e)}")

    parsed_url = urlparse(image_url)
    _img_ua = USER_AGENT  # S88：场景 2 会被 UA 配置覆盖
    
    # --- 场景 1: 内部文件路径处理 ---
    if 'uploaded_files' in parsed_url.path:
        HOST = get_host()
        PORT = get_port()
        if HOST == '0.0.0.0': HOST = '127.0.0.1'
        
        # 【安全动作】使用 sanitize_url 强制重写 netloc，切断原始输入流
        safe_target_url = sanitize_url(image_url, force_netloc=f"{HOST}:{PORT}")
        # 回连本服务器：自签名 https 场景跳过 TLS 校验
        no_ssl_verify = True
    
    # --- 场景 2: 公网 URL 爬取 ---
    else:
        # S85-D4：代理激活时域名跳过本地 DNS 预判定（fake-ip/污染会误杀）
        from py.proxy_util import (active_proxy as _active_proxy,
                                   is_literal_ip as _is_literal_ip, http_ua as _http_ua)
        _st = await load_settings()
        _px = _active_proxy(_st)
        _img_ua = _http_ua(_st, USER_AGENT)  # S88：UA 配置注入图像抓取
        _bypass_dns_check = bool(_px) and not _is_literal_ip(parsed_url.hostname)
        # A. SSRF 安全拦截（受"网络访问控制"开关门控：本机等价∨局域网）
        if _bypass_dns_check:
            internal_source = False
        elif is_private_ip(parsed_url.hostname):
            if not await ssrf_gate(parsed_url.hostname, 'image'):
                raise PermissionError(f"安全拒绝: 不允许从内部网络获取图像 ({parsed_url.hostname}){NET_BLOCK_HINT}")
            internal_source = True
            logging.getLogger("app").info(f"[SSRF] 已放行内部图像源: {parsed_url.hostname}")
        else:
            internal_source = False

        # B. Robots.txt 检查（放行的内部源跳过；代理激活时经代理拉取）
        if not internal_source and not await check_robots_txt(image_url, proxy_url=_px):
            raise PermissionError(f"合规拒绝: 目标网站禁止爬虫抓取该图像")

        # C. 【安全动作】清洗外部 URL，生成扫描器认可的 safe_url
        safe_target_url = sanitize_url(image_url)
        # 门控放行的内部源同样豁免 TLS 校验（自签证书常态），公网保持完整校验
        no_ssl_verify = internal_source

    # --- 执行下载 ---（S85-D：_make_session 统一处理 http/socks 代理与解析器）
    _dl_proxy = None if no_ssl_verify else _px
    async with _make_session(proxy_url=_dl_proxy) as session:
        # 统一使用 safe_target_url 发起请求
        headers = {'User-Agent': _img_ua}
        try:
            async with session.get(safe_target_url, headers=headers, timeout=20, ssl=(False if no_ssl_verify else None)) as response:
                if response.status != 200:
                    raise ValueError(f"无法下载图片: HTTP {response.status}")
                image_data = await response.read()
        except aiohttp.ClientError as e:
            raise RuntimeError(f"图像下载请求失败: {e}")
        except asyncio.TimeoutError:
            raise RuntimeError("图像下载超时")
    return base64.b64encode(image_data).decode('utf-8')

async def get_llm_tool(settings):
    llm_list = []

    llmTools = settings['llmTools']

    for llmTool in llmTools:
        if llmTool['enabled']:
            llm_list.append({"name": llmTool['name'], "description": llmTool['description']})
    if len(llm_list) > 0:
        llm_list = json.dumps(llm_list, ensure_ascii=False, indent=4)
        llm_tool = {
            "type": "function",
            "function": {
                "name": "custom_llm_tool",
                "description": f"custom_llm_tool工具可以调用工具列表中的通用工具。请不要混淆custom_llm_tool和tool_name字段要填入的工具名称。以下是工具列表：\n{llm_list}\n\n如果LLM工具返回的内容包含图片，则返回的图片URL或本地路径，请直接写成：![image](图片URL)格式发给用户，用户就能看到图片了",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tool_name": {
                            "type": "string",
                            "description": "需要调用的工具名称",
                        },
                        "query": {
                            "type": "string",
                            "description": "需要向工具发送的问题",
                        },
                        "image_url": {
                            "type": "string",
                            "description": "需要向工具发送的图片URL或本机本地文件路径，可选。服务器内部URL默认仅支持 /uploaded_files 路由下的图片（在设置开启「网络访问控制」放行开关后亦支持本机或局域网URL）；本地路径请使用当前操作系统的原生风格书写（Windows 如 C:\\Users\\name\\img.png，Linux/Mac 如 /home/user/img.png），会被自动处理为base64编码发送",
                        }
                    },
                    "required": ["tool_name","query"]
                }
            }
        }
        return llm_tool
    else:
        return None
        
_MAGIC_MEDIA = [
    (b'\x89PNG\r\n\x1a\n', 'image/png'),
    (b'\xff\xd8\xff', 'image/jpeg'),
    (b'GIF87a', 'image/gif'),
    (b'GIF89a', 'image/gif'),
    (b'BM', 'image/bmp'),
    (b'II*\x00', 'image/tiff'),
    (b'MM\x00*', 'image/tiff'),
]

def sniff_media_type_from_base64(b64_data: str) -> str:
    """按魔数嗅探真实 MIME，识别不了返回 ''"""
    try:
        head = base64.b64decode((b64_data or "")[:32])
    except Exception:
        return ''
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'image/webp'
    if head[4:8] == b'ftyp':
        return 'video/quicktime' if head[8:12] == b'qt  ' else 'video/mp4'
    if head[:4] == b'\x1a\x45\xdf\xa3':
        return 'video/webm'
    for magic, mt in _MAGIC_MEDIA:
        if head[:len(magic)] == magic:
            return mt
    return ''

async def get_image_media_type(image_url: str, base64_data: str = "") -> str:
    # 有实际数据时按字节魔数判定（URL 后缀对 /view?filename=x.jpg 之类的查询串 URL 不可靠）
    if base64_data:
        sniffed = sniff_media_type_from_base64(base64_data)
        if sniffed:
            return sniffed
    # 根据image_url类型调整
    if image_url.endswith('.png'):
        media_type = 'image/png'
    elif image_url.endswith('.jpg') or image_url.endswith('.jpeg'):
        media_type = 'image/jpeg'
    elif image_url.endswith('.webp'):
        media_type = 'image/webp'
    elif image_url.endswith('.gif'):
        media_type = 'image/gif'
    elif image_url.endswith('.bmp'):
        media_type = 'image/bmp'
    elif image_url.endswith('.tiff'):
        media_type = 'image/tiff'
    elif image_url.endswith('.ico'):
        media_type = 'image/x-icon'
    elif image_url.endswith('.svg'):
        media_type = 'image/svg+xml'
    elif image_url.endswith('.mp4'):
        media_type = 'video/mp4'
    elif image_url.endswith('.webm'):
        media_type = 'video/webm'
    elif image_url.endswith('.mov'):
        media_type = 'video/quicktime'
    elif image_url.endswith('.avi'):
        media_type = 'video/x-msvideo'
    else:
        media_type = 'image/png'
    return media_type

async def custom_llm_tool(tool_name, query, image_url=None):
    logging.getLogger("app").info(f"调用LLM工具：{tool_name}")
    settings = await load_settings()
    llmTools = settings['llmTools']
    for llmTool in llmTools:
        if llmTool['enabled'] and llmTool['name'] == tool_name:
            if llmTool['type'] == 'ollama':
                from ollama import AsyncClient as OllamaClient
                client = OllamaClient(host=llmTool['base_url'])
                try:
                    content = query
                    
                    # 处理图片输入
                    if image_url:
                        base64_image = await get_image_base64(image_url)
                        media_type = await get_image_media_type(image_url, base64_image)
                        content = [
                            {"type": "text", "text": query},
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": base64_image
                                }
                            }
                        ]

                    # 调用Ollama API
                    response = await client.chat(
                        model=llmTool['model'],
                        messages=[{"role": "user", "content": content}],
                    )
                    return response.message.content
                except Exception as e:
                    return f"Error: {str(e)}"
            else:
                client = AsyncOpenAI(api_key=llmTool['api_key'],base_url=llmTool['base_url'])
                try:
                    if image_url:
                        base64_image = await get_image_base64(image_url)
                        # 根据image_url类型调整
                        media_type = await get_image_media_type(image_url, base64_image)
                        prompt = [
                            {
                                "type": "image",
                                "image_url": {"url": f"data:{media_type};base64,{base64_image}"},
                            },
                            {
                                "type": "text",
                                "text": query
                            }
                        ]
                        async with llm_gate.gate():
                            response = await client.chat.completions.create(
                                model=llmTool['model'],
                                messages=[
                                    {"role": "user", "content": prompt},
                                ],
                            )
                    else:
                        async with llm_gate.gate():
                            response = await client.chat.completions.create(
                                model=llmTool['model'],
                                messages=[
                                    {"role": "user", "content": query},
                                ],
                            )
                    return response.choices[0].message.content
                except Exception as e:
                    return f"Error: {str(e)}"