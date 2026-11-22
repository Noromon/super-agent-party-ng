# -*- coding: utf-8 -*-
"""S191 IM 连续性：轮内链持久化（im_chain）、inflight 检查点、审批快照落盘。

覆盖：链帧增量累积与截断护栏、memoryList 展平、审批快照对抽取、
approval_store 重启恢复（含过期宽限与销账同步）、_merge_inflight 行为、
服务端检查点/流量标记 source 钉。
"""
import asyncio
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]


def _call_frame(tcid, name="read_file", args='{"path":"a.txt"}'):
    return {"type": "call", "title": name, "content": args}, tcid


def _result_frame(tcid, name="read_file", content="ok"):
    return {"type": "tool_result", "title": name, "content": content}, tcid


class TestChainUpdate:
    def test_call_and_result_pair(self):
        from py.im_chain import chain_update
        ch = None
        tc, tcid = _call_frame("t1")
        ch = chain_update(ch, tc, tcid)
        tc, tcid = _result_frame("t1")
        ch = chain_update(ch, tc, tcid)
        assert ch[0]["role"] == "assistant" and ch[0]["tool_calls"][0]["id"] == "t1"
        assert ch[0]["tool_calls"][0]["function"]["arguments"] == '{"path":"a.txt"}'
        assert ch[1] == {"role": "tool", "tool_call_id": "t1",
                         "name": "read_file", "content": "ok"}

    def test_no_tool_call_id_skipped(self):
        from py.im_chain import chain_update
        tc, _ = _call_frame("")
        assert chain_update(None, tc, "") is None

    def test_oversized_args_stays_valid_json(self):
        from py.im_chain import chain_update
        big = json.dumps({"p": "x" * 9000})
        tc, tcid = _call_frame("t2", args=big)
        ch = chain_update(None, tc, tcid)
        args = ch[0]["tool_calls"][0]["function"]["arguments"]
        json.loads(args)  # 不抛异常即合法
        assert "截断" in args or "_truncated_s191" in args

    def test_oversized_result_clipped(self):
        from py.im_chain import chain_update
        tc, tcid = _result_frame("t3", content="y" * 30000)
        ch = chain_update(None, tc, tcid)
        assert len(ch[0]["content"]) < 30000 and ch[0]["content"].endswith("[截断s191]")


class TestFlattenMemory:
    def test_chain_entries_expanded(self):
        from py.im_chain import flatten_memory
        mem = [
            {"role": "user", "content": "做点事"},
            {"role": "assistant", "content": "完成",
             "backend_content": [
                 {"role": "assistant", "content": "", "tool_calls": [{"id": "t1"}]},
                 {"role": "tool", "tool_call_id": "t1", "content": "r"}]},
            {"role": "user", "content": "继续"},
        ]
        flat = flatten_memory(mem)
        assert [m["role"] for m in flat] == ["user", "assistant", "tool",
                                             "assistant", "user"]
        assert flat[-1]["content"] == "继续"
        # 普通条目只留 role/content 两键
        assert set(flat[0].keys()) == {"role", "content"}

    def test_pairs_from_snapshot_strips_system(self):
        from py.im_chain import pairs_from_snapshot
        snap = [
            {"role": "system", "content": "契约"},
            {"role": "user", "content": "任务"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "t1"}]},
            {"role": "tool", "tool_call_id": "t1", "content": "r"},
            {"role": "assistant", "content": "普通文本"},
        ]
        pairs = pairs_from_snapshot(snap)
        assert [(m["role"], m.get("tool_call_id", "")) for m in pairs] == [
            ("assistant", ""), ("tool", "t1")]

    def test_merge_inflight_appends_pairs_entry(self):
        from py.im_chain import merge_inflight
        mem = [{"role": "user", "content": "旧"}]
        ent = merge_inflight(mem, [
            {"role": "system", "content": "s"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "t9"}]},
            {"role": "tool", "tool_call_id": "t9", "content": "r"}])
        assert ent is not None and ent["content"] == ""
        assert mem[-1] is ent and len(ent["backend_content"]) == 2
        assert merge_inflight([], [{"role": "user", "content": "x"}]) is None


class TestApprovalSnapshot:
    def test_disk_roundtrip_survives_restart(self, tmp_path, monkeypatch):
        from py import approval_store as st
        monkeypatch.setattr(st, "_snapshot_dir_override", str(tmp_path))
        snap = [{"role": "user", "content": "任务"},
                {"role": "assistant", "content": "", "tool_calls": [{"id": "t1"}]},
                {"role": "tool", "tool_call_id": "t1", "content": "哨兵"}]

        async def _go():
            rec = await st.create(platform="xmpp", peer_id="j@x", tool_name="bash",
                                  messages=snap, ttl=600)
            f = tmp_path / "approvals_pending.json"
            assert f.exists()
            assert json.loads(f.read_text(encoding="utf-8"))[0]["approval_id"] \
                == rec["approval_id"]
            # 模拟进程重启：内存全清、句柄全丢
            for th in st._EXPIRE_TASKS.values():
                th.cancel()
            st._EXPIRE_TASKS.clear()
            st._PENDING.clear()
            st._INDEX.clear()
            n = await st.restore_pending()
            assert n == 1 and st.has_pending("xmpp", "j@x")
            r2, err = await st.resolve("xmpp", "j@x", "approve")
            assert r2 and r2["messages"][2]["content"] == "哨兵" and not err
            assert json.loads(f.read_text(encoding="utf-8")) == []
            st.clear_all()
        asyncio.run(_go())

    def test_expired_gets_restart_grace(self, tmp_path, monkeypatch):
        from py import approval_store as st
        monkeypatch.setattr(st, "_snapshot_dir_override", str(tmp_path))

        async def _go():
            await st.create(platform="xmpp", peer_id="j@z", tool_name="bash", ttl=1)
            rec = st._PENDING[next(iter(st._PENDING))]
            rec["expires_at"] = time.time() - 9999  # 模拟宕机中过期
            for th in st._EXPIRE_TASKS.values():
                th.cancel()
            st._EXPIRE_TASKS.clear()
            st._PENDING.clear()
            st._INDEX.clear()
            assert await st.restore_pending() == 1
            assert st.has_pending("xmpp", "j@z")  # 宽限窗内仍可批复
            st.clear_all()
        asyncio.run(_go())

    def test_clear_all_removes_file(self, tmp_path, monkeypatch):
        from py import approval_store as st
        monkeypatch.setattr(st, "_snapshot_dir_override", str(tmp_path))

        async def _go():
            await st.create(platform="xmpp", peer_id="j@c", tool_name="bash")
            assert (tmp_path / "approvals_pending.json").exists()
            st.clear_all()
            assert not (tmp_path / "approvals_pending.json").exists()
        asyncio.run(_go())


class TestXmppMergeInflight:
    def test_merge_and_clear(self, monkeypatch):
        import pytest
        pytest.importorskip("slixmpp")
        import py.xmpp_client as xc

        calls = {"del": []}

        async def fake_load(key):
            if key.endswith("#inflight"):
                return [{"role": "system", "content": "s"},
                        {"role": "assistant", "content": "",
                         "tool_calls": [{"id": "t1"}]},
                        {"role": "tool", "tool_call_id": "t1", "content": "r"}]
            return []

        async def fake_del(key):
            calls["del"].append(key)

        monkeypatch.setattr(xc.gs_mod, "load_bot_conv", fake_load)
        monkeypatch.setattr(xc.gs_mod, "delete_bot_conv", fake_del)
        obj = object.__new__(xc.XmppClient)
        obj.memoryList = {"j": [{"role": "user", "content": "旧"}]}
        asyncio.run(obj._merge_inflight("j"))
        tail = obj.memoryList["j"][-1]
        assert tail.get("backend_content") and tail["content"] == ""
        assert calls["del"] == ["bot:xmpp:j#inflight"]
        asyncio.run(obj._clear_inflight("j"))
        assert calls["del"][-1] == "bot:xmpp:j#inflight"


class TestSourcePins:
    def test_server_checkpoint_and_traffic_tags(self):
        s = ((_ROOT / "server.py").read_text(encoding="utf-8") + (_ROOT / "py" / "stream_prep.py").read_text(encoding="utf-8") + (_ROOT / "py" / "stream_engine.py").read_text(encoding="utf-8")
 + (_ROOT / "py" / "stream_response.py").read_text(encoding="utf-8")
 + (_ROOT / "py" / "complete_engine.py").read_text(encoding="utf-8"))  # S304：响应装配/批复执行域迁出，合并面守恒（体逐字未动）  # S302a：流式域迁 stream_prep/stream_engine，文本钉合并扫描（体逐字未动）
        assert '#inflight' in s and "_tool_loop_count % 5 == 0" in s
        assert 'user="sap-reasoner"' in s and s.count('user="sap-reasoner"') == 4
        assert s.count('user="sap-main"') == 2
        assert '"reasoner_enabled"' in s

    def test_xmpp_chain_wiring(self):
        s = (_ROOT / "py" / "xmpp_client.py").read_text(encoding="utf-8")
        assert "im_chain.flatten_memory" in s
        assert "_merge_inflight" in s and "_clear_inflight" in s
        assert 'res.get("chain")' in s
        assert "restore_pending" in s
