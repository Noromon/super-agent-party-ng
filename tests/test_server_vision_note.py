# -*- coding: utf-8 -*-
"""Contract pins for server._append_note (extracted via AST to avoid the
heavy server import): str content concatenates, list content gains a
proper text part — never a character-by-character splat."""
import ast
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parent.parent / "server.py"


@pytest.fixture(scope="module")
def append_note():
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    fn = next((n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == "_append_note"), None)
    assert fn is not None, "_append_note missing from server.py"
    ns = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "server", "exec"), ns)
    return ns["_append_note"]


class TestAppendNote:
    def test_str_concatenates(self, append_note):
        assert append_note("hello", " note") == "hello note"

    def test_list_gains_text_part(self, append_note):
        content = [{"type": "image_url", "image_url": {"url": "data:x"}},
                   {"type": "text", "text": "look"}]
        out = append_note(content, "\n\nsystem: desc\n\n")
        assert len(out) == 3
        assert out[2] == {"type": "text", "text": "\n\nsystem: desc\n\n"}
        assert out[:2] == content          # original not mutated
        assert content == [{"type": "image_url", "image_url": {"url": "data:x"}},
                           {"type": "text", "text": "look"}]

    def test_never_splats_characters(self, append_note):
        out = append_note([{"type": "text", "text": "a"}], "note")
        for item in out:
            assert isinstance(item, dict)   # no single-char strings in parts
