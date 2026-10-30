import time
import logging
import datetime
import httpx

from py.get_setting import get_port
from py.diary_system import append_diary_entry, DEFAULT_BOOK_ID

_chat_buffers = {}


def get_chat_buffer(key: str):
    if key not in _chat_buffers:
        _chat_buffers[key] = {
            "messages": [],
            "last_user_msg_time": time.time(),
            "last_activity_time": time.time(),  # S173：assistant 回复也刷新（真空闲语义）
            "book_id": DEFAULT_BOOK_ID,
            "character_name": "",
        }
    return _chat_buffers[key]


def append_to_chat_buffer(key: str, role: str, content: str):
    buf = get_chat_buffer(key)
    buf["messages"].append({"role": role, "content": str(content)[:2000]})
    if len(buf["messages"]) > 200:
        buf["messages"] = buf["messages"][-200:]
    # S173：空闲=用户沉默 且 对话本身无产出。旧语义只随 user 消息重置，
    # agent 连续执行超过 idleMinutes 的长任务期间被误判「空闲」触发总结（事故实证）。
    buf["last_activity_time"] = time.time()
    if role == "user":
        buf["last_user_msg_time"] = time.time()


def update_buffer_identity(key: str, book_id: str = None, character_name: str = ""):
    buf = get_chat_buffer(key)
    if book_id:
        buf["book_id"] = book_id
    if character_name:
        buf["character_name"] = character_name


def get_idle_buffers(idle_minutes: int = 15):
    now = time.time()
    idle_threshold = now - idle_minutes * 60
    result = []
    for key, buf in list(_chat_buffers.items()):
        if not buf["messages"]:
            continue
        # S173：真空闲——用户最后消息 与 最后一次任何产出（含 assistant 回复）
        # 双双超过 idleMinutes 才算空闲；agent 忙（流在跑/刚回复完）一律不入选。
        _last_act = buf.get("last_activity_time") or buf.get("last_user_msg_time", 0)
        if buf["last_user_msg_time"] < idle_threshold and _last_act < idle_threshold:
            result.append((key, buf))
    return result


def clear_chat_buffer(key: str):
    buf = _chat_buffers.get(key)
    if buf:
        buf["messages"] = []
        buf["last_user_msg_time"] = time.time()
        buf["last_activity_time"] = time.time()


_RETRY_AFTER: dict = {}  # key -> 失败后下次允许重试的时间戳（S172：失败退避，防每分钟自调用风暴）
_RETRY_COOLDOWN = 300.0


async def summarize_and_save_buffers(idle_minutes: int = 15):
    idle_list = get_idle_buffers(idle_minutes)
    if not idle_list:
        return
    _now = time.time()
    for key, buf in idle_list:
        if _now < _RETRY_AFTER.get(key, 0.0):
            continue
        try:
            messages_text = ""
            for m in buf["messages"][-50:]:
                role_label = "用户" if m["role"] == "user" else "助手"
                messages_text += f"[{role_label}]: {m['content']}\n"
            if not messages_text.strip():
                clear_chat_buffer(key)
                _RETRY_AFTER.pop(key, None)
                continue

            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            sys_prompt = (
                f"当前时间：{now_str}。用户已经 {idle_minutes} 分钟没有与你对话。"
                "请将下方最近的对话记录总结为一篇简短的日记，用第一人称、自然真诚地书写。"
                "只需要总结要点、用户的需求或情绪、以及你的想法，不需要逐条复述。"
                "这是一次纯文本写作任务：禁止调用任何工具/技能，不要操作文件或命令，直接输出日记正文。"
            )
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": f"[最近的对话记录]:\n{messages_text}"},
            ]

            port = get_port()
            url = f"http://127.0.0.1:{port}/v1/chat/completions"
            payload = {
                "model": "super-model",
                "messages": messages,
                "stream": False,
                "is_app_bot": True,
                "platform": "diary",
                "enable_tools": [],
            }
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                summary = (data.get("choices", [{}])[0]
                           .get("message", {})
                           .get("content", "") or "").strip()
            if summary:
                title = summary.strip().splitlines()[0][:24] if summary.strip() else ""
                await append_diary_entry("chatSummary", summary, title=title,
                                         book_id=buf["book_id"],
                                         character_id=buf["book_id"] if buf["book_id"] != DEFAULT_BOOK_ID else None,
                                         character_name=buf.get("character_name", ""))
                logging.info(f"[DiaryChat] 已自动总结对话到日记 [{buf['book_id']}]")
            clear_chat_buffer(key)
            _RETRY_AFTER.pop(key, None)
        except Exception as e:
            # S172：失败不再于下个 60s tick 立即重放——退避 5 分钟；异常打 repr 防空消息
            _RETRY_AFTER[key] = time.time() + _RETRY_COOLDOWN
            logging.error(f"[DiaryChat] 总结对话失败 [{key}]（{_RETRY_COOLDOWN:.0f}s 后重试）: {e!r}")
