"""上传类端点的超时必须传给 ``_request``。

2026-10-29 live 事故：6MB PDF 走 ``/Msg/SendFile``，客户端全局 ``timeout=30`` 直接超时。
超时无法区分「没发出去」和「发出去了但响应丢了」，而微信消息撤不回 —— 所以上传端点
必须有独立的、更长的超时（``UPLOAD_TIMEOUT``），而且这个值要真的传到 aiohttp 那一层。

写法对齐本仓既有风格（``asyncio.run``，不用 pytest-asyncio）。
"""

from __future__ import annotations

import asyncio

from plugin.core.api_client import UPLOAD_TIMEOUT, WppClient


def _client() -> WppClient:
    return WppClient(base_url="https://wpp.test/api/v1/gateway", authcode="wxa_test",
                     account_id="t", audit=False)


def test_send_file_uses_upload_timeout():
    seen = {}

    async def fake_call(endpoint, body=None, method="POST", max_retries=2, *, audit=True, timeout=None):
        seen["endpoint"], seen["timeout"], seen["body"] = endpoint, timeout, body
        return {"Code": 0}

    c = _client()
    c.call = fake_call  # type: ignore[assignment]
    asyncio.run(c.send_file_v2("q123456789", "方案.pdf", "QUJD"))
    assert seen["endpoint"] == "/Msg/SendFile"
    assert seen["timeout"] == UPLOAD_TIMEOUT
    assert seen["body"]["FileName"] == "方案.pdf"


def test_send_image_uses_upload_timeout():
    seen = {}

    async def fake_call(endpoint, body=None, method="POST", max_retries=2, *, audit=True, timeout=None):
        seen["endpoint"], seen["timeout"] = endpoint, timeout
        return {"Code": 0}

    c = _client()
    c.call = fake_call  # type: ignore[assignment]
    asyncio.run(c.send_image("q123456789", "QUJD"))
    assert seen["endpoint"] == "/Msg/UploadImg"
    assert seen["timeout"] == UPLOAD_TIMEOUT


def test_call_forwards_timeout_to_request():
    """``call(timeout=...)`` 是唯一入口 ⇒ 必须原样传进 ``_request``（aiohttp 那一层）。"""
    seen = {}

    async def fake_request(endpoint, body, *, method, max_retries, audit=True,
                           path_targets=(), timeout=None):
        seen["timeout"] = timeout
        return {"Code": 0}

    c = _client()
    c._request = fake_request  # type: ignore[assignment]
    asyncio.run(c.call("/Msg/SendFile", {"x": 1}, max_retries=0, timeout=42.5))
    assert seen["timeout"] == 42.5

    asyncio.run(c.call("/User/GetContractProfile"))
    assert seen["timeout"] is None  # 普通端点沿用 self.timeout，不被改动
