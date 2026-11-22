# build=S299
# S294：/api/wheel-state 全局滚轮真相通道（WH_MOUSE_LL 钩子累加，拉取即清零）。
# 测试不拉起真钩子：monkeypatch _wheel_install，直接驱动累加器验证 drain 语义。
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_mod = sys.modules.get("py")
if _mod is not None and not hasattr(_mod, "__path__"):
    del sys.modules["py"]  # site-packages 同名遮蔽清除（项目惯例）

SRC = (ROOT / "py" / "routers" / "island.py").read_text(encoding="utf-8")


def test_endpoint_shape():
    assert '@router.get("/api/wheel-state")' in SRC
    assert "SetWindowsHookExW(14" in SRC  # WH_MOUSE_LL
    assert "0x020A" in SRC  # WM_MOUSEWHEEL
    assert "platform.system() != \"Windows\"" in SRC  # 非 win 静默（delta 恒 0）
    assert "_wheel_cb_ref" in SRC  # 回调强引用：GC 掉原生钩子指针=崩溃


def test_drain_semantics():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from py.routers import island

    island._wheel_install = lambda: None  # 测试进程不装真钩子
    island._wheel_delta = 0
    app = FastAPI()
    app.include_router(island.router)
    c = TestClient(app)
    assert c.get("/api/wheel-state").json() == {"delta": 0}
    island._wheel_delta = 240
    assert c.get("/api/wheel-state").json() == {"delta": 240}
    assert c.get("/api/wheel-state").json() == {"delta": 0}  # drain：拉取即清零
