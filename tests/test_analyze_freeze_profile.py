# S98: CPU profile 分析器合成自测（不依赖真 profile 文件）
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_freeze_profile import analyze  # noqa: E402


def _synthetic_profile(path: Path) -> None:
    nodes = [
        {"id": 1, "callFrame": {"functionName": "", "url": "", "lineNumber": -1, "columnNumber": 0}, "children": [2]},
        {"id": 2, "callFrame": {"functionName": "renderAll", "url": "http://127.0.0.1:3456/js/renderer.js",
                                "lineNumber": 100, "columnNumber": 0}, "children": [3]},
        {"id": 3, "callFrame": {"functionName": "formatMessage", "url": "http://127.0.0.1:3456/js/methods/08_message_render.js",
                                "lineNumber": 87, "columnNumber": 0}, "children": []},
    ]
    prof = {
        "nodes": nodes,
        "samples": [3, 3, 3, 2, 3],
        "timeDeltas": [1000, 1000, 1000, 500, 1000],
    }
    path.write_text(json.dumps(prof), encoding="utf-8")


def test_analyze_orders_hot_frames(tmp_path):
    p = tmp_path / "sap-freeze-profile-x.json"
    _synthetic_profile(p)
    out = analyze(str(p))
    assert "samples=5" in out
    # formatMessage 4000/4500us(88.9%) 必须排在 renderAll 500us(11.1%) 之前
    fmt_line = next(line for line in out.splitlines() if "formatMessage" in line)
    ren_line = next(line for line in out.splitlines() if "renderAll" in line)
    assert out.index(fmt_line) < out.index(ren_line)
    assert "88.9%" in fmt_line
    assert "08_message_render.js" in fmt_line
    assert "renderer.js" in out.split("--- self-time by file ---")[1]
