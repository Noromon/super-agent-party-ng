# -*- coding: utf-8 -*-
"""S205 提示词组装块注册表：golden 永久字节钉。

tests/data/s205_prompt_literals.json 于 fe82755e 时点用 AST 从
server.tools_change_messages 抽取的静态字面量原文。任何对这些提示词的改动
必须显式更新 golden 文件（=有意的提示词变更评审），防止无意漂移。
"""
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]
GOLDEN = json.loads((_ROOT / "tests" / "data" / "s205_prompt_literals.json").read_text(encoding="utf-8"))
import py.prompt_assembly as pa  # noqa: E402
SERVER = (_ROOT / "server.py").read_text(encoding="utf-8")


class TestGolden:
    def test_constants_byte_identical(self):
        for name, text in GOLDEN.items():
            assert getattr(pa, name) == text, name

    def test_blocks_registry_complete(self):
        assert set(pa.BLOCKS.values()) == set(GOLDEN.values())
        assert len(pa.BLOCKS) == len(GOLDEN) == 7


class TestServerMigration:
    def test_server_uses_registry(self):
        for name in GOLDEN:
            assert re.search(rf"\b{name}\b", SERVER), name

    def test_big_literals_left_server(self):
        for probe in ("已安装的主要开发工具", "Linux (WSL2) | Shell", "静音标签",
                      "自主行为系统向你发送的消息", "行内公式定界符",
                      "思考推理的过程必须放在"):
            assert probe not in SERVER, probe

    def test_sticker_wiring_intact(self):
        assert "content_append(request.messages, 'system', STICKER_IMAGE_RULE)" in SERVER
        i = SERVER.index("if settings[\"stickerPacks\"]:")
        j = SERVER.index("_append_avatar_prompts", i)
        assert 0 < j - i < 2000  # sticker 块结构完整（曾发生吞换行合并事故）
