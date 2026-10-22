# -*- coding: utf-8 -*-
"""P3 A5 日记系统移植钩子冒烟（S65）。

不启动实例：importlib 直载 diary 模块（site-packages py 遮蔽，S59 教训），
校验 server.py / tool_assembly.py 挂点存在 + diary 数据链路自洽
（tmp USER_DATA_DIR 下的 append → query → list_books）。
"""
import asyncio
import importlib.util as ilu
import io
import re
import sys
import types
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = ilu.spec_from_file_location(name, str(_ROOT / rel))
    mod = ilu.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def diary_pkg(tmp_path_factory):
    # 桩 py 包绕开 site-packages py 遮蔽（S59/S63 同款保存-替换-恢复模式）
    data = tmp_path_factory.mktemp("diary-data")
    pkg = types.ModuleType("py")
    pkg.__path__ = [str(_ROOT / "py")]
    saved = {k: sys.modules.get(k) for k in ("py", "py.get_setting", "py.diary_system")}
    sys.modules["py"] = pkg
    sys.modules.pop("py.get_setting", None)
    sys.modules.pop("py.diary_system", None)
    try:
        import py.diary_system as ds  # type: ignore
        ds.USER_DATA_DIR = str(data)
        yield ds, data
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def test_server_hooks_present():
    src = io.open(_ROOT / "server.py", encoding="utf-8-sig").read()
    assert "from py.diary_query_tool import diary_query_tool" in src
    assert '"query_diary": handle_query_diary' in src
    assert '"list_diary_books": handle_list_diary_books' in src
    assert src.count('"query_diary": handle_query_diary') == 2  # 双份 hook 表都挂
    assert "global_diary_engine.update_config" in src  # lifespan + ws save 热更新
    assert "global_diary_engine.stop()" in src
    assert "include_router(diary_router)" in src
    assert "[角色日记 - 近期回忆]" in src  # 注入块
    assert src.count("append_to_chat_buffer(buffer_key") == 2  # user+assistant
    assert '"diary_query_tool": diary_query_tool' in src  # toolkit keys


def test_tool_assembly_gate():
    src = io.open(_ROOT / "py/tool_assembly.py", encoding="utf-8-sig").read()
    assert 'settings.get("diarySettings")' in src
    assert 'tk["diary_query_tool"]' in src
    assert 'tk["diary_books_tool"]' in src


def test_diary_files_bom_free_and_no_bare_print():
    for f in ["diary_system.py", "diary_engine.py", "diary_api.py",
              "diary_query_tool.py", "diary_chat_integration.py"]:
        raw = (_ROOT / "py" / f).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f
        src = raw.decode("utf-8")
        assert "print(" not in src, f + " 必须走 logging（M-5 棘轮）"


def test_append_query_books_roundtrip(diary_pkg):
    ds, _data = diary_pkg

    async def run():
        book = "char_" + uuid.uuid4().hex[:8]
        ok = await ds.append_diary_entry(
            "chatSummary", "今天和用户聊了移植计划", title="闲聊总结",
            book_id=book,
        )
        assert ok
        hits = await ds.query_diary_entries(query="移植", book_id=book)
        assert any("移植计划" in h.get("content", "") for h in hits), hits
        books = await ds.list_diary_books()
        assert any(b.get("bookId") == book for b in books), books
        # 默认兜底本恒在
        assert any(b.get("bookId") == ds.DEFAULT_BOOK_ID for b in books), books
    asyncio.run(run())


def test_api_router_wiring():
    import inspect
    ds = _load  # noqa: F841  (确保 fixture 依赖顺序无副作用)
    src = io.open(_ROOT / "py/diary_api.py", encoding="utf-8").read()
    assert 'APIRouter(prefix="/api/diary"' in src
    for ep in ["/books", "/get_data", "/save_data", "/delete", "/query"]:
        assert f'"{ep}"' in src, ep
    # server 必须在 status 之后 include（/api/diary 无鉴权豁免需求，走常规中间件）
    ssrc = io.open(_ROOT / "server.py", encoding="utf-8-sig").read()
    assert ssrc.index("app.include_router(status.router)") < ssrc.index("include_router(diary_router)")
    assert inspect  # noqa: F401


def test_frontend_wiring():
    html = io.open(_ROOT / "static/index.html", encoding="utf-8-sig").read()
    assert '<script src="js/methods/44_diary.js"></script>' in html
    assert html.index('44_diary.js') < html.index('<script src="js/renderer.js">')
    role = io.open(_ROOT / "static/templates/page_role.html", encoding="utf-8-sig").read()
    assert "subMenu === 'diary'" in role
    # S67：主动发消息渠道须含 XMPP（引擎 _push_to_im 走 behavior handler 通用路径，xmpp 已注册）
    assert 'label="XMPP" value="xmpp"' in role
    data = io.open(_ROOT / "static/js/data/60_cards_options.js", encoding="utf-8-sig").read()
    assert "diarySettings:" in data and "diaryActionMeta:" in data
    tiles = io.open(_ROOT / "static/js/data/40_tts_voice.js", encoding="utf-8-sig").read()
    assert "{ id: 'diary', title: 'DiarySystem'" in tiles
    schema = io.open(_ROOT / "static/js/settings_schema.js", encoding="utf-8-sig").read()
    assert "['diarySettings', 'diarySettings']" in schema
    for loc in ["zh-CN", "en-US"]:
        s = io.open(_ROOT / ("static/js/locales/%s.js" % loc), encoding="utf-8-sig").read()
        assert "'diarySaveSuccess'" in s or "DiarySystem" in s
        assert re.search(r"'DiarySystem'\s*:", s), loc


def test_diary_block_nested_in_suite_content():
    # S65.1 回归 pin：diary 子块必须在 .suite-content 内（尾插 EOF 曾致设置页空白）
    role = io.open(_ROOT / "static/templates/page_role.html", encoding="utf-8-sig").read()
    assert role.count("subMenu === 'diary'") == 1
    i_content = role.index('class="suite-content"')
    i_diary = role.index("subMenu === 'diary'")
    assert i_content < i_diary
    tail = [ln.strip() for ln in role.splitlines() if ln.strip()]
    assert tail[-3:] == ["</div>", "</div>", "</div>"]
    assert role.count("<div") == role.count("</div>")


def test_ws_diary_entry_branch_and_mainjs_cdp_always_on():
    # S65.1 缺口修补 pin：ws 分发器有 diary_entry 分支；main.js CDP 常开不再条件包裹
    ws = io.open(_ROOT / "static/js/methods/14_ws_client.js", encoding="utf-8-sig").read()
    assert "data.type === 'diary_entry'" in ws
    assert "this.pushDiaryToChat(" in ws and "'system_notify'" in ws
    mj = io.open(_ROOT / "main.js", encoding="utf-8-sig").read()
    assert "app.commandLine.appendSwitch('remote-debugging-port', '0');" in mj
    assert "chromeMCPSettings?.type === 'internal'" not in mj
    assert "IS_INTERNAL_MODE_ACTIVE = true;" in mj
