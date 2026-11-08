# -*- coding: utf-8 -*-
"""S203 IM 行为/主动外发轮尸块防护（真实事故样本回归）。

事故：行为轮经 /v1 非流分支返回正文（原样送 IM 对端），模型把 add_diary 调用块
写进正文——该分支无 S183 守卫，整块 <tool_call> markup 直接发到用户 XMPP。
修复=behavior_trigger 强制零工具+plain 注记（诱导面消除）+ _ns_behavior_sanitize
兜底剥除（漏网面消除）。
"""
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

SERVER = (_ROOT / "server.py").read_text(encoding="utf-8")

# 用户实收样本（2026-11-08 17:55 xmpp）
_LEAK_BODY = (
    "下午快六点啦～主人今天一直在聊硬件，插一句无厘头的：我贝雷帽上那颗星星肯定是间谍！\n\n"
    "<tool_call><function=add_diary>\n"
    "<parameter=content>\n"
    "下午快六点，我主动找主人搭话，抛了个自己瞎想的梗：贝雷帽右侧那颗带丝带的五角星"
    "如果是真星星派来的间谍，等于我天天顶着个监听器。\n"
    "</parameter>\n<parameter=type>\nthink\n</parameter>\n<parameter=importance>\n2\n</parameter>\n"
    '<parameter=tags>\n["日常闲聊", "主动搭话", "贝雷帽"]\n</parameter>\n'
    "<parameter=delay_ms>\n300\n</parameter>\n</function>\n</tool_call>"
)


def _sanitize(content):
    import server
    d = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    return server._ns_behavior_sanitize(d)["choices"][0]["message"]["content"]


class TestSanitizeRealSample:
    def test_greeting_survives_block_stripped(self):
        out = _sanitize(_LEAK_BODY)
        assert "星星肯定是间谍" in out          # 该发的招呼语保留
        for marker in ("tool_call", "add_diary", "delay_ms", "think", "[malformed"):
            assert marker not in out           # 尸块与占位符零残留

    def test_pure_block_becomes_empty(self):
        block = _LEAK_BODY[_LEAK_BODY.index("<tool_call>"):]
        assert _sanitize(block) == ""          # 纯尸块→空串→manager 不发送

    def test_clean_content_untouched(self):
        assert _sanitize("今天天气不错，出来玩吗？") == "今天天气不错，出来玩吗？"


class TestNsBehaviorWiring:
    def test_request_field(self):
        assert "behavior_trigger: bool = False" in SERVER

    def test_force_no_tools_before_first_call(self):
        body = SERVER[SERVER.index("async def _generate_complete_impl"):]
        i_guard = body.index('if getattr(request, "behavior_trigger", False):')
        i_first = body.index("msg = await images_add_in_messages")
        assert i_guard < i_first
        seg = body[i_guard:i_first]
        assert "tools = []" in seg and '"name": "system_note"' in seg

    def test_sanitize_wired_after_finalize(self):
        i_fin = SERVER.index("response_dict = await _complete_finalize")
        i_ret = SERVER.index("return JSONResponse(content=response_dict)")
        seg = SERVER[i_fin:i_ret]
        assert "_ns_behavior_sanitize(response_dict)" in seg
        i_helper = SERVER.index("def _ns_behavior_sanitize(")
        assert i_helper < i_fin

    def test_all_im_managers_declare_flag(self):
        names = ["dingtalk_bot_manager", "discord_bot_manager", "feishu_bot_manager",
                 "slack_bot_manager", "telegram_client", "wechat_bot_manager",
                 "wecom_bot_manager", "xmpp_client"]
        for n in names:
            src = (_ROOT / "py" / f"{n}.py").read_text(encoding="utf-8")
            assert '"behavior_trigger": True' in src, n


class TestNoRegexRegression:
    def test_re_module_available_in_server(self):
        assert re.search(r"^import re$", SERVER, re.M)
