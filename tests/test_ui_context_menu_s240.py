# -*- coding: utf-8 -*-
"""S240：UI 右键菜单——AI 浏览器标签条 + 会话列表。接线静态断言 + closeTabsAction
node 行为测（批量关标签的激活/保留语义）。"""
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(*p):
    return (ROOT.joinpath(*p)).read_text(encoding="utf-8")


MAIN = _read("main.js")
PRELOAD = _read("static", "js", "preload.js")
RENDERER = _read("static", "js", "renderer.js")
TABS = _read("static", "js", "methods", "98_browser_tabs.js")
GROUPS = _read("static", "js", "methods", "64_conversation_groups.js")
BAR = _read("static", "templates", "page_chat_bar.html")
HOST_INDEX = _read("static", "index.html")
CHAT = _read("static", "templates", "page_chat_main.html")
HOME = _read("static", "templates", "page_home.html")


def _extract_js_method(src, name):
    start = src.index(name + "(")
    brace = src.index("{", start)
    depth, i = 0, brace
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1
    raise AssertionError("unbalanced method: " + name)


def _run_close_tabs(tabs, cur, action, tab_id):
    """node 行为测：注入真实方法源码，返回执行后的 {ids, cur, called}。"""
    method = _extract_js_method(TABS, "closeTabsAction")
    script = f"""
const vm = {{
  browserTabs: {json.dumps(tabs)},
  currentTabId: {json.dumps(cur)},
  _called: null,
  closeTab(id) {{ this._called = 'closeTab:' + id; }},
  addNewTab() {{ this.browserTabs.push({{"id": 999, "url": ""}}); this.currentTabId = 999; }},
  switchTab(id) {{ this.currentTabId = id; }},
  {method}
}};
vm.closeTabsAction({json.dumps(action)}, {json.dumps(tab_id)});
process.stdout.write(JSON.stringify({{
  ids: vm.browserTabs.map(t => t.id), cur: vm.currentTabId, called: vm._called
}}));
"""
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


T = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]


def test_close_others():
    r = _run_close_tabs(T, 2, "closeOthers", 2)   # 目标=当前 → 保留目标且仍激活
    assert r == {"ids": [2], "cur": 2, "called": None}
    r = _run_close_tabs(T, 1, "closeOthers", 3)   # 目标≠当前(当前被关) → 激活目标
    assert r == {"ids": [3], "cur": 3, "called": None}


def test_close_left_right():
    r = _run_close_tabs(T, 1, "closeLeft", 3)     # 当前被关 → 激活被右键目标
    assert r == {"ids": [3, 4], "cur": 3, "called": None}
    r = _run_close_tabs(T, 4, "closeLeft", 3)     # 当前在保留区 → 不动
    assert r == {"ids": [3, 4], "cur": 4, "called": None}
    r = _run_close_tabs(T, 4, "closeRight", 2)
    assert r == {"ids": [1, 2], "cur": 2, "called": None}
    r = _run_close_tabs(T, 1, "closeRight", 2)    # 当前在保留区
    assert r == {"ids": [1, 2], "cur": 1, "called": None}


def test_close_single_and_all_delegate():
    r = _run_close_tabs(T, 1, "close", 2)         # 单个关=委托 closeTab(含末位语义)
    assert r["called"] == "closeTab:2" and r["ids"] == [1, 2, 3, 4]
    r = _run_close_tabs(T, 2, "closeAll", 2)      # 全关=清空+新干净标签
    assert r["ids"] == [999] and r["cur"] == 999


def test_missing_tab_noop():
    r = _run_close_tabs(T, 1, "closeAll", 777)
    assert r == {"ids": [1, 2, 3, 4], "cur": 1, "called": None}


# ---------------- 接线静态断言 ----------------

def test_template_bindings():
    # S241：必须 .stop——全局 document 兜底监听在冒泡顶端，不断流就会被二次覆盖。
    # S242 教训：标签条存在双源（宿主 index.html 内联副本 + templates/page_chat_bar
    # 锚点版），宿主内联=用户实机界面；改拆分模板时必须 grep 同名 class 补内联副本，
    # 此处双源各自钉死断言防再漏。
    assert '@contextmenu.prevent.stop="openTabContextMenu(tab)"' in BAR
    assert '@contextmenu.prevent.stop="openTabContextMenu(tab)"' in HOST_INDEX
    assert '@contextmenu.prevent.stop="openConvContextMenu(conv)"' in CHAT
    assert '@contextmenu.prevent.stop="openConvContextMenu(conv)"' in HOME
    # 内联副本与会话行不得在宿主内联重复出现而缺绑定（双源审计哨兵）
    assert HOST_INDEX.count('class="ib-tab"') == HOST_INDEX.count('openTabContextMenu(tab)')
    assert "history-item-row" not in HOST_INDEX  # 会话行仅锚点装配, 若内联化须同步补绑定


def test_global_listener_yields_to_handled_menus():
    """S241 根因：vue_data.js 全局 document contextmenu 兜底曾无条件弹 default
    菜单，把元素级专属菜单盖掉。守卫必须先于任何 showContextMenu 调用。"""
    vd = _read("static", "js", "vue_data.js")
    guard = vd.index("if (e.defaultPrevented) return;")
    assert guard < vd.index("showContextMenu('default')")
    assert guard < vd.index("showContextMenu('image'")


def test_vue_methods_exist():
    for token in ("openTabContextMenu", "tabReloadOne", "tabCopyUrl",
                  "tabDuplicate", "closeTabsAction",
                  "showContextMenu('browser-tab'"):
        assert token in TABS
    assert "openUrlInNewTab(tab.url, tab.partition)" in TABS   # duplicate 保留出口分区
    for token in ("openConvContextMenu", "handleConversationAction",
                  "showContextMenu('conversation'", "this.isTyping"):
        assert token in GROUPS
    assert "moveConversationToGroup(convId, groupId)" in GROUPS
    assert "confirmDeleteConversation(convId)" in GROUPS


def test_ipc_plumbing():
    assert "'browser-tab-action', 'conversation-action'" in PRELOAD  # validChannels 白名单
    assert "ipcRenderer.on('browser-tab-action'" in RENDERER
    assert "ipcRenderer.on('conversation-action'" in RENDERER
    assert "this.closeTabsAction(action, tabId)" in RENDERER
    assert "this.handleConversationAction(action, convId, groupId)" in RENDERER


def test_main_menu_branches_and_locales():
    assert "menuType === 'browser-tab'" in MAIN
    assert "menuType === 'conversation'" in MAIN
    assert "send('browser-tab-action'" in MAIN
    assert "send('conversation-action'" in MAIN
    assert "submenu: groups.map" in MAIN                      # 移动到分组=动态子菜单
    for key in ("tabReload", "tabDuplicate", "tabCloseLeft", "convMoveToGroup"):
        assert MAIN.count(key + ":") >= 2                     # zh+en 双份
    # 无 URL 的标签：复制/重复置灰
    assert "enabled: hasUrl" in MAIN


def test_stamp_s240():
    assert "build=S254" in _read("static", "js", "renderer.js")
