# build=S290
# S288：发言冷却下限 60s→5s（用户要求）。后端 py/screen_speak.py 用 _num 直读
# 无下限钳制（本文件回归锁死这一事实，防止日后有人加 floor 把 UI 改动架空）。
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLE = (ROOT / "static" / "templates" / "page_role.html").read_text(encoding="utf-8")
SPEAK = (ROOT / "py" / "screen_speak.py").read_text(encoding="utf-8")


def test_ui_min_lowered():
    assert 'v-model="screenWatchSettings.speak.cooldownSeconds" :min="5" :max="7200" :step="5"' in ROLE


def test_backend_has_no_floor():
    assert '_num(cfg, "cooldownSeconds", 600)' in SPEAK
    assert 'cooldownSeconds", 60)' not in SPEAK  # 默认 600 保持；无 60s 下限读取
    assert "max(60" not in SPEAK
