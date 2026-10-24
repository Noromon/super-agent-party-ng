# -*- coding: utf-8 -*-
"""S91(THA)：桌宠引擎契约——45 维姿态表/五官索引/mix 语义/渲染/模型管理。"""
import os
import pathlib
import sys
import tempfile

os.environ.setdefault("SAP_DATA_DIR", tempfile.mkdtemp(prefix="sap_s91e_"))
_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from py.tha_engine import (EMOTION_POSE_MAP, THA_MOTIONS,  # noqa: E402
                           _FACE_CONTROL_INDICES, THAModelManager,
                           THAPoseGenerator, get_engine)

LYRA_ONNX = _ROOT / "tha_models" / "Lyra" / "model.onnx"


def test_emotion_map_contract():
    assert sorted(EMOTION_POSE_MAP) == ["angry", "happy", "neutral",
                                        "relaxed", "sad", "surprised"]
    for name, pose in EMOTION_POSE_MAP.items():
        assert pose.shape == (45,), name
        assert pose.dtype == np.float32
        if name != "neutral":
            assert float(np.abs(pose).max()) > 0, f"{name} 位姿全零"


def test_fine_control_tokens_in_range():
    for token in ("eyebrow_troubled", "eyebrow_raised", "eye_happy",
                  "eye_unimpressed", "wink_left", "wink_right",
                  "mouth_smile", "mouth_smirk", "iris_small"):
        assert token in _FACE_CONTROL_INDICES, token
    for token, (indices, gain) in _FACE_CONTROL_INDICES.items():
        for i in indices:
            assert 0 <= int(i) < 45, token
        assert 0 < float(gain) <= 2.0, token


def test_motions_table():
    assert {"nod", "shakeHead", "tiltHead", "bow", "sway", "lookAround"} <= set(THA_MOTIONS)


def test_pose_generator_lifecycle():
    gen = THAPoseGenerator()
    p0 = gen.step()
    assert len(p0) == 45 and np.all(np.isfinite(p0))

    gen.set_emotion("happy")
    for _ in range(90):
        p = gen.step()
    idx = int(np.nonzero(EMOTION_POSE_MAP["happy"])[0][0])
    assert p[idx] > 0  # 平滑趋近目标位姿生效

    gen.set_emotion_mix({"happy": 0.5, "surprised": 0.4})
    for _ in range(30):
        p = gen.step()
    assert np.all(np.isfinite(p))

    gen.set_motion("nod")
    p = gen.step()
    assert np.all(np.isfinite(p))
    gen.clear_motion()
    gen.set_mouth(0.7)
    gen.set_mouse(0.5, -0.5)
    assert np.all(np.isfinite(gen.step()))


def test_engine_render_jpeg_and_cache():
    if not LYRA_ONNX.exists():
        pytest.skip("Lyra 默认模型不在仓")
    engine = get_engine(str(LYRA_ONNX))
    jpeg = engine.render(np.zeros(45, dtype=np.float32), 85)
    assert isinstance(jpeg, (bytes, bytearray))
    assert jpeg[:3] == b"\xff\xd8\xff" and len(jpeg) > 2000
    assert get_engine(str(LYRA_ONNX)) is engine  # 缓存命中


def test_model_manager_scan_and_guards(tmp_path):
    user_dir = tmp_path / "user"
    mgr = THAModelManager(str(_ROOT / "tha_models"), str(user_dir))
    defaults = mgr.scan_default_models()
    assert any(m["id"] == "Lyra" for m in defaults)
    assert mgr.scan_user_models() == []
    assert user_dir.exists()  # 缺失时自动建目录

    ok, msg, _ = mgr.install_onnx(b"junk", "../evil")
    assert not ok and "非法" in msg
    ok2, msg2, _ = mgr.install_onnx(b"junk", "ok_name")
    assert ok2
    assert (user_dir / "ok_name" / "model.onnx").exists()
    assert mgr.delete_model("no-such") is False
    assert mgr.delete_model("ok_name") is True
    assert not (user_dir / "ok_name").exists()


def test_upload_rejects_bad_zip(tmp_path):
    mgr = THAModelManager(str(tmp_path / "d"), str(tmp_path / "u"))
    ok, msg, _ = mgr.install_mlpackage(b"not-a-zip", "badpkg")
    assert not ok and ("ZIP" in msg or "无效" in msg)
    assert not (tmp_path / "u" / "badpkg").exists()  # 失败已回滚
