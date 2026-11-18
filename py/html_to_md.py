# -*- coding: utf-8 -*-
"""S227: HTML -> Markdown 统一转换工具（本地，无云）。

供窥屏/浏览器两条链路复用：
- render_page：离屏 webview 渲染动态页后取回清洗过的 HTML，转 Markdown 给 agent；
- get_page_markdown：把当前活动标签页就地转 Markdown。

优先使用 markdownify；缺失时退回 bs4 纯文本兜底（bs4 已是核心依赖）。
始终做体量截断，避免把 MB 级页面灌进上下文。
"""
import logging
import re

_STRIP_TAGS = [
    "script", "style", "noscript", "template", "svg", "canvas",
    "nav", "footer", "header", "aside", "form", "iframe",
    "video", "audio", "picture", "button", "input", "select", "option",
]

_LINKED = ["a", "h1", "h2", "h3", "h4", "h5", "h6", "img"]


def _log():
    return logging.getLogger("app")


def _prettify(html: str) -> str:
    """移除噪声标签并回收链接/标题/正文，尽量保住可读结构。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html or "", "html.parser")
    for t in soup(_STRIP_TAGS):
        t.decompose()
    # S246: data: URI 图对模型无意义且会撑爆体量——就地摘除
    for img in soup.find_all("img"):
        src = img.get("src") or ""
        if src.startswith("data:"):
            img.replace_with("[img:data-uri omitted]")
    body = soup.body or soup
    return str(body)


def _collapse(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _denoise(md: str) -> str:
    """S246: 重复膨胀熔断——字体未加载/CSS 损坏页会向文本注入整屏重复串（如
    'mmmm…li'），淹没有效正文。同字符长 run 与短 token 高次连排折叠并标注；
    连续相同行 >=8 折叠为计数行。正常内容几乎不触发。"""
    if not md:
        return md
    # 阈值取垃圾级（同字符>=60 / 短序列连排>=20 次）：正常中英文几乎不可能触及，
    # 而字体/CSS 损坏注入的膨胀串动辄数百上千字符必被命中。
    md = re.sub(r"([^\n])\1{59,}", lambda m: m.group(1) * 3 + "…[repeat collapsed]", md)
    # {2,6}: 序列须多字符——单字符已由上行 60 阈值处理，否则等价于 run>=20 误伤中文
    md = re.sub(r"([^\s\n]{2,6})\1{19,}", lambda m: m.group(1)[:6] + "…[repeat collapsed]", md)
    lines = md.split("\n")
    out, i, n = [], 0, len(lines)
    while i < n:
        j = i
        while j < n and lines[j] == lines[i]:
            j += 1
        run = j - i
        if lines[i].strip() and run >= 8:
            out.append(lines[i])
            out.append(f"[repeated pattern collapsed ×{run - 1}]")
        else:
            out.extend(lines[i:j])
        i = j
    return "\n".join(out)


def html_to_markdown(html: str, max_chars: int = 120000) -> str:
    """把 HTML 转成 Markdown 文本，做长度截断。

    max_chars<=0 表示不截断。异常一律退化为 bs4 纯文本，绝不抛出。
    """
    if not html or not str(html).strip():
        return ""
    try:
        cleaned = _prettify(html)
    except Exception as e:  # noqa: BLE001
        _log().info(f"html_to_md preformat failed: {e}")
        cleaned = html
    md = ""
    try:
        from markdownify import markdownify as _md
        # S246: img 不再剥离——内容图输出为 ![](url)，关键证据常在图里，
        # agent 可拿 url 直接走 view_images 一手查看
        md = _md(
            cleaned,
            heading_style="ATX",
            bullets="-",
            strip=["picture", "svg", "canvas", "video", "audio", "iframe"],
        )
    except Exception as e:  # noqa: BLE001
        _log().info(f"markdownify unavailable/failed, fallback to text: {e}")
        md = _text_fallback(cleaned)
    md = _denoise(_collapse(md or ""))
    if max_chars and max_chars > 0 and len(md) > max_chars:
        md = md[:max_chars] + f"\n\n...[truncated {len(md) - max_chars} chars]"
    return md


def _text_fallback(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(html or "", "html.parser").get_text("\n", strip=True)
    except Exception:  # noqa: BLE001
        return re.sub(r"<[^>]+>", " ", html or "")
