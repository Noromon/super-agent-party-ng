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
    body = soup.body or soup
    return str(body)


def _collapse(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
        md = _md(
            cleaned,
            heading_style="ATX",
            bullets="-",
            strip=["img", "picture", "svg", "canvas", "video", "audio", "iframe"],
        )
    except Exception as e:  # noqa: BLE001
        _log().info(f"markdownify unavailable/failed, fallback to text: {e}")
        md = _text_fallback(cleaned)
    md = _collapse(md or "")
    if max_chars and max_chars > 0 and len(md) > max_chars:
        md = md[:max_chars] + f"\n\n...[truncated {len(md) - max_chars} chars]"
    return md


def _text_fallback(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(html or "", "html.parser").get_text("\n", strip=True)
    except Exception:  # noqa: BLE001
        return re.sub(r"<[^>]+>", " ", html or "")
