# -*- coding: utf-8 -*-
"""从 E:\\Temp\\log.txt 的 `all msg:` 终端转储恢复丢失会话。

用法:
  python py/recover_from_log.py            # 解析+存档到 E:\\Temp\\recovered，不写库
  python py/recover_from_log.py --import   # 另经 WS save_conversations_delta 写入 SAP
"""
import ast
import asyncio
import json
import os
import sys
import uuid

LOG = r"E:\Temp\log.txt"
OUT = r"E:\Temp\recovered"
DUMPS = {  # 0-based line index of the '[PY]' channel dump (the app: channel dup is skipped)
    "A": [818],
    "B": [1324, 1328],
}
TITLES = {
    "A": "chara-dataset-incubator 技能设计（从日志恢复）",
    "B": "qwen-image-edit 批量质检规则（从日志恢复）",
}
TIMESTAMPS = {"A": 1792262630961, "B": 1792263579427}  # 日志中最后 dump 时刻
WS_URL = "ws://127.0.0.1:3456/ws"


def load_lines():
    return open(LOG, "rb").read().decode("utf-8", errors="replace").splitlines()


def parse_dump(lines, li):
    raw = lines[li]
    i = raw.find("all msg: ")
    return ast.literal_eval(raw[i + 9:].strip())


def merge(session):
    lines = load_lines()
    dumps = [parse_dump(lines, li) for li in DUMPS[session]]
    base = list(dumps[0])
    for later in dumps[1:]:
        seen = {m.get("content") for m in base if m.get("role") == "assistant" and m.get("content")}
        tail_new = False
        for m in later:
            if m.get("role") == "assistant":
                tail_new = bool(m.get("content")) and m["content"] not in seen
                if tail_new:
                    base.append(m)
                    seen.add(m["content"])
            elif m.get("role") == "tool" and tail_new:
                base.append(m)
    return [m for m in base if m.get("role") != "system"]


def _text_blocks(msg):
    blocks = []
    rc = msg.get("reasoning_content") or ""
    if rc.strip():
        blocks.append({"type": "text", "id": None, "name": None,
                       "content": "<|channel>thought\n" + rc, "args": None, "data": None})
    c = msg.get("content") or ""
    if c.strip():
        blocks.append({"type": "text", "id": None, "name": None,
                       "content": c, "args": None, "data": None})
    return blocks


def build_ui_messages(msgs, id_base):
    ui, i, seq = [], 0, 0

    def nid():
        nonlocal seq
        seq += 1
        return id_base + seq / 1000.0

    while i < len(msgs):
        m = msgs[i]
        if m.get("role") == "user":
            ui.append({
                "id": nid(), "role": "user", "content": m.get("content") or "",
                "fileLinks": [], "fileLinks_content": "", "imageLinks": [],
                "hasDesktopVision": False, "agentName": "主人",
                "currentChunk": 0, "omniCurrentTime": 0, "audioChunks": [],
                "omniAudioChunks": [], "isPlaying": False,
            })
            i += 1
            continue
        # assistant round: this assistant + all directly following tool items
        group = [m]
        j = i + 1
        while j < len(msgs) and msgs[j].get("role") == "tool":
            group.append(msgs[j])
            j += 1
        tool_results = {t.get("tool_call_id"): t.get("content") or "" for t in group[1:]}
        blocks, texts = [], []
        for tc in (group[0].get("tool_calls") or []):
            fn = tc.get("function", {})
            blocks.append({"type": "tool_call", "id": tc.get("id"), "name": fn.get("name"),
                           "content": "", "args": "[" + (fn.get("arguments") or "") + "]", "data": None})
            res = tool_results.get(tc.get("id"))
            if res is not None:
                blocks.append({"type": "tool_result", "id": tc.get("id"), "name": fn.get("name"),
                               "content": res, "args": None, "data": None})
        blocks.extend(_text_blocks(group[0]))
        main = group[0].get("content") or ""
        if main.strip():
            texts.append(main)
        ui.append({
            "id": nid(), "role": "assistant", "agentName": "默认智能体",
            "content": main, "pure_content": main,
            "backend_content": group, "toolBlocks": {}, "displayBlocks": blocks,
            "isOmni": False, "ttsChunks": [], "chunks_voice": [], "total_tokens": 0,
            "first_token_latency": 0, "elapsedTime": 0, "generationFinished": True,
            "currentChunk": 0, "omniCurrentTime": 0, "audioChunks": [],
            "omniAudioChunks": [], "isPlaying": False,
        })
        i = j
    return ui


def build_conv(session, msgs):
    return {
        "id": str(uuid.uuid4()), "title": TITLES[session], "mainAgent": "super-model",
        "groupId": "default", "timestamp": TIMESTAMPS[session],
        "messages": build_ui_messages(msgs, TIMESTAMPS[session]),
        "fileLinks": [], "system_prompt": "",
    }


def archive(session, conv, msgs):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, f"{session}_recovered.json"), "w", encoding="utf-8") as f:
        json.dump({"conversation": conv, "backend_messages": msgs}, f, ensure_ascii=False, indent=1)
    md = [f"# {conv['title']}", ""]
    for m in msgs:
        if m.get("role") == "user":
            md += ["## 用户", "", m.get("content") or "", ""]
        elif m.get("role") == "assistant":
            if m.get("reasoning_content"):
                md += ["> **[thinking]**", *["> " + l for l in m["reasoning_content"].splitlines()], ""]
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function", {})
                md += [f"- 🔧 `{fn.get('name')}({(fn.get('arguments') or '')[:160]})`"]
            if m.get("content"):
                md += ["## 助手", "", m["content"], ""]
        elif m.get("role") == "tool":
            c = (m.get("content") or "")[:600]
            md += [f"<details><summary>📄 工具结果（截断存档）</summary>\n\n```\n{c}\n```\n\n</details>", ""]
    with open(os.path.join(OUT, f"{session}_recovered.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))


async def push(convs):
    import aiohttp

    async def wait_type(ws, t, timeout=30):
        while True:
            msg = await asyncio.wait_for(ws.receive(timeout=timeout), timeout)
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            try:
                d = json.loads(msg.data)
            except Exception:
                continue
            if d.get("type") == t:
                return d

    async with aiohttp.ClientSession() as s:
        async with s.ws_connect(WS_URL, heartbeat=None, max_msg_size=0) as ws:
            await wait_type(ws, "settings", 25)
            cid = uuid.uuid4().hex
            await ws.send_str(json.dumps({
                "type": "save_conversations_delta",
                "data": {"conversations": convs}, "correlationId": cid,
            }, ensure_ascii=False))
            ack = await wait_type(ws, "conversations_delta_saved", 60)
            print("ack:", ack and ack.get("correlationId") == cid, ack and ack.get("success"))


def main():
    do_import = "--import" in sys.argv
    convs = []
    for session in ("A", "B"):
        msgs = merge(session)
        conv = build_conv(session, msgs)
        archive(session, conv, msgs)
        n_user = sum(1 for m in msgs if m.get("role") == "user")
        n_asst = sum(1 for m in msgs if m.get("role") == "assistant")
        n_tool = sum(1 for m in msgs if m.get("role") == "tool")
        print(f"[{session}] backend={len(msgs)} (u{n_user}/a{n_asst}/t{n_tool}) ui={len(conv['messages'])} "
              f"title={conv['title']}")
        print(f"   first user: {str(msgs[0].get('content'))[:60]}")
        convs.append(conv)
    print("archive ->", OUT)
    if do_import:
        asyncio.run(push(convs))


if __name__ == "__main__":
    main()
