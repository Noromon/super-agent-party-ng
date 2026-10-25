# -*- coding: utf-8 -*-
"""S120(R1a): 静态资源内容版本号注入 + SW sap-cache-v2（上游 e03cedb3 移植）。"""
import re

import requests


def test_main_document_versioned_and_nocache(sap):
    r = requests.get(f"{sap}/", timeout=15)
    assert r.status_code == 200
    assert "no-cache" in r.headers.get("Cache-Control", "")
    # index.html 引用的 js/css 被改写为 ?v=<8位hex>
    assert re.search(r'(?:src|href)="[^"]+\.(?:js|css)\?v=[a-f0-9]{8}"', r.text)


def test_swjs_is_v2_policy(sap):
    r = requests.get(f"{sap}/sw.js", timeout=15)
    assert r.status_code == 200
    assert "sap-cache-v2" in r.text
    assert "my-pwa-cache-v1" not in r.text


def test_json_endpoint_untouched_by_injector(sap):
    r = requests.get(f"{sap}/health", timeout=15)
    assert r.status_code == 200
    # 非 HTML 响应不被版本化中间件当 HTML 处理
    assert "text/html" not in r.headers.get("content-type", "")

