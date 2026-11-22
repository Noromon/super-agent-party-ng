# build=S278
# S271：屏幕旁观每日发言上限放宽到 99999（用户要求）。后端 _num 从不钳制上限，
# 唯一门槛一直是这个输入框的 :max=20——放开它即可。
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_daily_limit_input_max_raised():
    html = (ROOT / "static/templates/page_role.html").read_text(encoding="utf-8")
    i = html.index("screenWatchSettings.speak.dailyLimit")
    seg = html[i - 200:i + 300]
    assert ':max="99999"' in seg and ':min="1"' in seg
    assert ':max="20"' not in seg


def test_backend_has_no_hard_cap():
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
        del sys.modules["py"]
    import py.screen_speak as ss
    # 99999 原样读回——后端无钳制，改配置即生效
    assert ss._num({"dailyLimit": 99999}, "dailyLimit", 5) == 99999
    # 默认值不变（未配置仍 5 条）
    assert ss._num({}, "dailyLimit", 5) == 5
