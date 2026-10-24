# -*- coding: utf-8 -*-
"""S90：浏览器搜索引擎——用内置 Electron webview 作为搜索执行引擎。

背景（2026-10-24 实测）：用户出口 IP 被 DDG 全面风控（html/lite/main 三入口
对 primp/requests 一律 202），但内置浏览器全指纹+JS 可正常打开搜索。设计
原则＝"浏览器能打开＝能搜"：专属模板优先，也接受任意 URL 模板走通用抽取。

浏览器引擎默认顺序：ddg → brave → cnbing → baidu → so360（用户拍板：
brave 首批收录、排在 ddg 之后）。
协议口径（实测 80_webview_agent.js / cdp_tool.py）：
- getPagesInfo → JSON 字符串 [{index,id,title,url,active}]
- openUrlInNewTab 新 tab 自动成为 active
- executeInActiveWebview 对象自动 stringify；错误返回 "Error..." /
  "JS Execution Error: ..." 字符串
- evaluate 的 JS 文本不得含 "location" / "submit()"（cdp_tool 导航拦截会把
  调用转成 setTimeout 异步壳，拿不到返回值）
"""
import asyncio
import json
import logging
from urllib.parse import quote

def log():
    return logging.getLogger("app")

ENGINE_TEMPLATES = {
    "ddg": "https://duckduckgo.com/?q={q}",
    "brave": "https://search.brave.com/search?q={q}",
    "cnbing": "https://cn.bing.com/search?q={q}",
    "bing": "https://www.bing.com/search?q={q}",
    "baidu": "https://www.baidu.com/s?wd={q}",
    "so360": "https://www.so.com/s?q={q}",
}
BROWSER_ORDER = ["ddg", "brave", "cnbing", "baidu", "so360"]

# settings['webSearch']['engine'] → 浏览器模板名（None＝无同族模板，走默认顺序）
def browser_equiv(engine):
    return {"duckduckgo": "ddg", "bing": "cnbing", "brave": "brave",
            "google": None, "searxng": None, "tavily": None, "exa": None,
            "serper": None, "bochaai": None, "youcom": None}.get(engine)


_JS_HEADER = """
var sigs = ["unusual traffic", "too many requests", "captcha",
            "are you a robot", "access denied", "verify you are human",
            "\\u767e\\u5ea6\\u5b89\\u5168\\u9a8c\\u8bc1", "\\u4eba\\u673a\\u9a8c\\u8bc1",
            "\\u5b89\\u5168\\u9a8c\\u8bc1"];
var bt = ((document.body && document.body.innerText) || "").slice(0, 4000).toLowerCase();
var anti = "";
for (var i = 0; i < sigs.length; i++) {
    if (bt.indexOf(sigs[i]) >= 0) { anti = sigs[i]; break; }
}
function T(e) { return e ? (e.innerText || "").replace(/\\s+/g, " ").trim() : ""; }
function clip(s, n) { return s.length > n ? s.slice(0, n) : s; }
function out(rs) {
    return JSON.stringify({ ready: document.readyState, anti: anti,
                            n: rs.length, results: rs.slice(0, 10) });
}
"""


def _mk_js(body):
    return "function() {" + _JS_HEADER + body + "}"


_JS_BODIES = {
    "ddg": """
var rs = [];
var arts = document.querySelectorAll(
    '[data-testid="result"], article[data-result="web"]');
for (var i = 0; i < arts.length && rs.length < 10; i++) {
    var a = arts[i].querySelector(
        'a[data-testid="result-title-a"], h2 a, h3 a');
    if (!a) continue;
    var sn = arts[i].querySelector(
        '[data-result="snippet"], [data-result="body"]');
    rs.push({ t: T(a), u: a.href, s: clip(T(sn), 160) });
}
return out(rs);
""",
    "brave": """
var rs = [];
var ds = document.querySelectorAll('div.snippet[data-type="web"], div.snippet');
for (var i = 0; i < ds.length && rs.length < 10; i++) {
    var a = ds[i].querySelector('a[href^="http"]');
    if (!a) continue;
    var tt = ds[i].querySelector('.title, [role="heading"]');
    var sn = ds[i].querySelector('.snippet-description, p');
    rs.push({ t: T(tt || a), u: a.href, s: clip(T(sn), 160) });
}
return out(rs);
""",
    "bing": """
var rs = [];
var lis = document.querySelectorAll('li.b_algo');
for (var i = 0; i < lis.length && rs.length < 10; i++) {
    var a = lis[i].querySelector('h2 a');
    if (!a) continue;
    var sn = lis[i].querySelector('p, .b_caption');
    rs.push({ t: T(a), u: a.href, s: clip(T(sn), 160) });
}
return out(rs);
""",
    "baidu": """
var rs = [];
var cs = document.querySelectorAll('div.c-container, div[tpl]');
for (var i = 0; i < cs.length && rs.length < 10; i++) {
    if (cs[i].getAttribute("data-source") === "ads") continue;
    var a = cs[i].querySelector('h3 a');
    if (!a) continue;
    var u = cs[i].getAttribute("mu") || a.href;
    var sn = cs[i].querySelector(
        '[class*="abstract"], [class*="content-right"]');
    rs.push({ t: T(a), u: u, s: clip(T(sn), 160) });
}
return out(rs);
""",
    "so360": """
var rs = [];
var lis = document.querySelectorAll('li.res-list, li[class*="res-list"]');
for (var i = 0; i < lis.length && rs.length < 10; i++) {
    var a = lis[i].querySelector('h3 a');
    if (!a) continue;
    var sn = lis[i].querySelector('p.a-p, .res-desc');
    rs.push({ t: T(a), u: a.href, s: clip(T(sn), 160) });
}
return out(rs);
""",
    "general": """
var rs = [];
var seen = {};
var as = document.querySelectorAll('h3 a[href^="http"], h2 a[href^="http"]');
for (var i = 0; i < as.length && rs.length < 10; i++) {
    var u = as[i].href;
    if (seen[u]) continue;
    seen[u] = 1;
    var box = as[i].closest("div, li") || as[i].parentElement;
    rs.push({ t: T(as[i]), u: u, s: clip(T(box), 120) });
}
return out(rs);
""",
}
# cnbing/www bing 同 DOM
_JS_BODIES["cnbing"] = _JS_BODIES["bing"]
JS_TABLE = {k: _mk_js(v) for k, v in _JS_BODIES.items()}

browser_search_tool = {
    "type": "function",
    "function": {
        "name": "browser_lookup",
        "description": ("通过内置浏览器发起搜索（真实 Chromium 指纹，可访问对 HTTP "
                        "客户端风控严格的站点如 DuckDuckGo）。engine 省略时按默认顺序"
                        "ddg→brave→cnbing→baidu→so360 依次尝试；engine 也可为含 {q} "
                        "占位符的搜索页 URL 模板（任意搜索引擎，配通用抽取）。"),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "搜索关键词，多个词语用空格隔开。"},
                "engine": {"type": "string",
                           "description": ("可选：ddg/brave/cnbing/bing/baidu/so360，"
                                           "或含 {q} 占位符的 URL 模板。")},
            },
            "required": ["query"],
        },
    },
}


def _err(msg):
    return (f"[Error] 浏览器搜索失败：{msg}\n"
            "[引导] 可改用浏览器工具自行搜索：new_page(搜索URL) → "
            "take_snapshot 或 evaluate_script 提取；或在设置中更换搜索引擎。")


async def browser_available():
    try:
        from py.cdp_tool import get_targets
        return bool(await get_targets())
    except Exception:
        return False


async def _read_pages():
    from py.cdp_tool import list_pages
    info = await list_pages()
    if isinstance(info, list):
        return info
    if isinstance(info, str):
        try:
            data = json.loads(info)
            return data if isinstance(data, list) else []
        except Exception:
            return []
    return []


async def _open_or_reuse(url):
    """复用同 host 的搜索标签页导航，否则新开标签页。返回是否操作成功。"""
    from py.cdp_tool import navigate_page, new_page, select_page
    host = url.split("/")[2] if "://" in url else ""
    idx = None
    for p in await _read_pages():
        if host and host in (p.get("url") or ""):
            idx = p.get("index")
            break
    if idx is not None:
        await select_page(idx)
        r = await navigate_page(type="url", url=url)
    else:
        r = await new_page(url)
    s = str(r)
    return not (s.startswith("Error") or s.startswith("Failed")
                or s.startswith("Main window not found"))


async def _extract(js, per_engine):
    """轮询 evaluate。返回 (state, data)：ok/anti/empty。"""
    from py.cdp_tool import evaluate_script
    waited, last = 0.0, None
    while waited < per_engine:
        r = await evaluate_script(js)
        last = r
        if isinstance(r, str) and r.startswith("{"):
            try:
                d = json.loads(r)
            except Exception:
                d = None
            if isinstance(d, dict):
                if d.get("anti"):
                    return "anti", d
                if d.get("n", 0) > 0:
                    return "ok", d
        elif isinstance(r, str) and (r.startswith("Error")
                                     or r.startswith("JS Execution Error")):
            return "empty", {"err": r[:120]}
        await asyncio.sleep(1.0)
        waited += 1.0
    return "empty", last


def _resolve_target(engine):
    """engine → (展示名, URL 模板名, JS 名)。engine 可为模板名或含 {q} 的 URL。"""
    if engine and engine.startswith("http") and "{q}" in engine:
        return "custom", engine, "general"
    if engine and engine in ENGINE_TEMPLATES:
        return engine, engine, engine
    return None, None, None


async def browser_search(query, engine=None, max_results=8):
    """浏览器搜索入口。engine=None → 默认顺序；显式 → 单引擎。"""
    budget = 20.0 if engine else 55.0
    try:
        return await asyncio.wait_for(
            _browser_search(query, engine, max_results), timeout=budget)
    except asyncio.TimeoutError:
        return _err(f"总超时（{int(budget)}s），内置浏览器未及时产出结果")
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def _browser_search(query, engine, max_results):
    if not await browser_available():
        return _err("内置浏览器通道不可用（此功能仅 Electron 桌面版有效，"
                    "或 CDP 未连接）")
    q = quote(query)
    if engine:
        name, url_tpl, js_key = _resolve_target(engine)
        if not name:
            return _err(f"未知 engine={engine!r}（可用：ddg/brave/cnbing/bing/"
                        f"baidu/so360 或含 {{q}} 的 URL 模板）")
        order = [(name, url_tpl, js_key)]
    else:
        order = [(e, e, e) for e in BROWSER_ORDER]

    per_engine = 14.0 if engine else 9.0
    errs = []
    for name, url_tpl, js_key in order:
        url = ENGINE_TEMPLATES.get(url_tpl, url_tpl).replace("{q}", q)
        try:
            if not await _open_or_reuse(url):
                errs.append(f"{name}: 标签页操作失败")
                continue
            state, data = await _extract(JS_TABLE[js_key], per_engine)
            if state == "ok":
                items = [{"title": r.get("t", ""), "url": r.get("u", ""),
                          "snippet": r.get("s", "")}
                         for r in (data or {}).get("results", [])][:max_results]
                if items:
                    return json.dumps(items, ensure_ascii=False, indent=2)
                errs.append(f"{name}: 抽取到空条目")
            elif state == "anti":
                sig = (data or {}).get("anti", "")
                errs.append(f"{name}: 被人机校验/限流拦截（{sig}）")
            else:
                errs.append(f"{name}: 未能抽取结果（加载慢或页面结构变化）")
        except Exception as e:
            errs.append(f"{name}: {type(e).__name__} {str(e)[:80]}")
    return _err("全部尝试引擎均失败：" + "；".join(errs))


def search_result_ok(text):
    """搜索结果判活：非空、非 [Error]、JSON 可解析且条目 ≥1。"""
    if not text or not str(text).strip():
        return False
    s = str(text).strip()
    if s.startswith("[Error]"):
        return False
    try:
        data = json.loads(s)
        return isinstance(data, list) and len(data) > 0
    except Exception:
        # 非 JSON 的纯文本结果（部分引擎原始返回）也算活
        return len(s) > 20


GUIDE_HINT = ("\n[引导] 本次网络搜索失败。你可以：1) 调用 browser_lookup 工具经"
              "内置浏览器搜索（可过 DuckDuckGo 等对 HTTP 客户端的风控）；"
              "2) 用浏览器工具 new_page/navigate_page/take_snapshot 自行打开"
              "搜索引擎页面提取；3) 换更短关键词重试。空结果不代表信息不存在。")
