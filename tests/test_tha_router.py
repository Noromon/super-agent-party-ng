# -*- coding: utf-8 -*-
"""S91(THA)：桌宠路由合同——配置回环/表情广播/模型管理/静态分发/WS 鉴权与帧流。

全部打真测试实例（sap fixture），WS 帧流做真 ONNX 推理收 JPEG。
"""
import io
import socket
import time

import requests

from test_token import tok


def _h(sap):
    return {"X-SAP-Token": tok(sap)}


def _port(sap):
    return sap.rstrip("/").split(":")[-1]


def _ws_handshake(sap, path, token=None):
    p = _port(sap)
    s = socket.create_connection(("127.0.0.1", p), timeout=30)
    try:
        tok_line = f"X-SAP-Token: {token}\r\n" if token else ""
        s.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{p}\r\n"
                   f"{tok_line}"
                   "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                   "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                   "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        return s, s.recv(400)
    except Exception:
        s.close()
        raise


class TestThaRouterContract:
    def test_config_roundtrip(self, sap):
        r = requests.get(f"{sap}/tha_config", timeout=15, headers=_h(sap))
        assert r.status_code == 200
        cfg = r.json().get("THAConfig", {})
        assert cfg.get("selectedModelId") == "Lyra"
        try:
            r2 = requests.post(f"{sap}/tha_config", json={"selectedModelId": "Other"},
                               timeout=15, headers=_h(sap))
            assert r2.status_code == 200 and r2.json().get("success") is True
            assert requests.get(f"{sap}/tha_config", timeout=15,
                                headers=_h(sap)).json()["THAConfig"]["selectedModelId"] == "Other"
        finally:  # session 级实例：必须还原，否则 WS 帧流用例找不到模型
            requests.post(f"{sap}/tha_config", json={"selectedModelId": "Lyra"},
                          timeout=15, headers=_h(sap))

    def test_emotion_endpoint_forms_and_guards(self, sap):
        ok_cases = [{"emotion": "happy"},
                    {"expressions": ["happy:0.3", "surprised:0.5"]},
                    {"emotions": {"happy": 0.3, "sad": 0.2}}]
        for body in ok_cases:
            r = requests.post(f"{sap}/tha_emotion", json=body, timeout=15, headers=_h(sap))
            assert r.status_code == 200 and r.json().get("success") is True, body
        bad_cases = [{"emotions": {"happy": "x"}}, {"expressions": "not-a-list"},
                     {"emotion": 42}, {}]
        for body in bad_cases:
            r = requests.post(f"{sap}/tha_emotion", json=body, timeout=15, headers=_h(sap))
            assert r.status_code == 400, body

    def test_model_listing_and_guards(self, sap):
        r = requests.get(f"{sap}/get_default_tha_models", timeout=15, headers=_h(sap))
        assert r.status_code == 200 and r.json().get("success") is True
        assert any(m["id"] == "Lyra" for m in r.json()["models"])
        r2 = requests.get(f"{sap}/get_user_tha_models", timeout=15, headers=_h(sap))
        assert r2.status_code == 200 and r2.json().get("models") == []
        r3 = requests.post(f"{sap}/upload_tha_model",
                           files={"file": ("bad.txt", io.BytesIO(b"x"), "text/plain")},
                           data={"display_name": "bad"}, timeout=15, headers=_h(sap))
        assert r3.status_code == 400
        r4 = requests.delete(f"{sap}/delete_tha_model/no-such-model",
                             timeout=15, headers=_h(sap))
        assert r4.status_code == 404

    def test_tha_models_static_served(self, sap):
        r = requests.get(f"{sap}/tha_models/Lyra/model.onnx", timeout=30,
                         headers=_h(sap), stream=True)
        assert r.status_code == 200
        head = r.raw.read(8)
        assert len(head) > 0  # onnx protobuf 头部即可（不拉 6.7MB 全量）
        r.close()


class TestThaWebSocket:
    def test_ws_requires_auth(self, sap):
        s, resp = _ws_handshake(sap, "/ws/tha", token=None)
        s.close()
        assert b"101" not in resp.split(b"\r\n", 1)[0], repr(resp[:80])

    def test_ws_streams_jpeg_frames(self, sap):
        s, resp = _ws_handshake(sap, "/ws/tha", token=tok(sap))
        try:
            assert b"101" in resp.split(b"\r\n", 1)[0], repr(resp[:80])
            s.settimeout(60)  # 首帧含 session 构建；慢环境/DirectML 初始化留足
            buf = bytearray(resp)
            deadline = time.time() + 60
            while time.time() < deadline:
                try:
                    chunk = s.recv(65536)
                except socket.timeout:
                    break
                if not chunk:
                    break
                buf.extend(chunk)
                if b"\xff\xd8\xff" in bytes(buf):
                    return  # JPEG 帧载荷出现 = 30fps 帧流已启动
            raise AssertionError(f"60s 内未收到 JPEG 帧（收 {len(buf)}B）")
        finally:
            s.close()
