# build=S296
# S264：本地推理服务器拒收 webp/avif 等格式（400 'url' field must be a base64 encoded image
# 炸整轮实证：twitter 图 format=webp）。注入层单点归一化转码 JPEG + 剥图重试补词兜底。
import base64
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py.llm_tool import _normalize_image_for_server, _SERVER_IMAGE_OK  # noqa: E402

SERVER = (ROOT / "server.py").read_text(encoding="utf-8")


def _img_bytes(fmt, size=(8, 8)):
    from PIL import Image
    img = Image.new("RGB", size, (120, 40, 200))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def test_webp_transcoded_to_jpeg():
    b64 = base64.b64encode(_img_bytes("WEBP")).decode()
    out_b64, mime = _normalize_image_for_server(b64, "image/webp")
    assert mime == "image/jpeg"
    assert base64.b64decode(out_b64)[:3] == b"\xff\xd8\xff"
    assert out_b64 != b64


def test_whitelist_passthrough():
    png_b64 = base64.b64encode(_img_bytes("PNG")).decode()
    out_b64, mime = _normalize_image_for_server(png_b64, "image/png")
    assert (out_b64, mime) == (png_b64, "image/png")
    assert {"image/jpeg", "image/png", "image/gif", "image/bmp"} <= _SERVER_IMAGE_OK


def test_animated_webp_first_frame():
    from PIL import Image
    frames = [Image.new("RGB", (6, 6), (i * 40, 10, 200)) for i in range(3)]
    buf = io.BytesIO()
    frames[0].save(buf, format="WEBP", save_all=True, append_images=frames[1:], duration=50)
    b64 = base64.b64encode(buf.getvalue()).decode()
    out_b64, mime = _normalize_image_for_server(b64, "image/webp")
    assert mime == "image/jpeg"
    assert base64.b64decode(out_b64)[:3] == b"\xff\xd8\xff"


def test_garbage_bytes_no_crash():
    out_b64, mime = _normalize_image_for_server("AAAA", "image/webp")
    assert (out_b64, mime) == ("AAAA", "image/webp")  # 转码失败返回原值兜底


def test_hook_mounted_in_images_in_messages():
    i = SERVER.index("def images_in_messages")
    seg = SERVER[i:i + 2200]
    assert "_normalize_image_for_server" in seg
    assert "data:%s;base64," % "{mime_type}" in seg or 'f"data:{mime_type};base64,"' in seg


def test_strip_retry_covers_base64_reject():
    i = SERVER.index("img_strip_retried")
    seg = SERVER[i:i + 700]
    assert '"base64 encoded image" in _et252' in seg
