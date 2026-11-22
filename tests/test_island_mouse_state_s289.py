# build=S290
# S289：/api/mouse-state 全局左键态端点（高 DPI 机 Blink 点击失效时 HUD 物理点击
# 通道的后端数据源）。端点逻辑必须薄——判定语义全在页面侧。
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
    assert '@router.get("/api/mouse-state")' in SRC
    assert "GetAsyncKeyState(0x01)" in SRC
    assert "& 0x8000" in SRC
    assert 'platform.system() != "Windows"' in SRC  # 非 win 恒 False（Linux/Docker 语义）


def test_endpoint_returns_bool():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from py.routers import island

    app = FastAPI()
    app.include_router(island.router)
    c = TestClient(app)
    r = c.get("/api/mouse-state")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("lbtn"), bool), body
