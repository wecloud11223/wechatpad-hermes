"""发送类端点**不重试**（2026-10-18 审阅修）。

## 为什么这条线是 P1

``_request`` 原来对所有端点默认 ``max_retries=2``。超时/连接断这两类失败**无法区分**
"请求没到厂商"和"厂商已经发出、响应丢了"。对读取闻端点重试是自愈；对发送端点重试
就是**给真实联系人再发一条** —— 微信消息撤不回（红线 3）。

修法：在唯一入口 ``WppClient.call`` 里按 ``outbound_guard.is_read_only`` 分类，
写端点一律把 ``max_retries`` 压成 0。这样通用端点表里那 216 个端点也自动覆盖，
不依赖每个调用点自己记得传参。

本文件用假 ``aiohttp`` 数**真实发出的请求次数**：写端点必须恰好 1 次（即使调用方
显式要求重试），读端点保留重试。
"""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

from plugin.core import api_client as api_mod
from plugin.core.api_client import WppApiError, WppClient


class _ClientError(Exception):
    pass


def _install_fake_aiohttp(monkeypatch, script: list[tuple]):
    """装一个假 aiohttp：``script`` 按序返回 ``(status, body[, headers])``，返回假 session。"""

    class _Resp:
        def __init__(self, status: int, text: str, headers: dict | None = None) -> None:
            self.status = status
            self._text = text
            self.headers = headers or {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def text(self) -> str:
            return self._text

    class _Sess:
        def __init__(self) -> None:
            self.calls = 0
            self.closed = False

        def request(self, method, url, **kw):        # noqa: ANN001
            idx = min(self.calls, len(script) - 1)
            self.calls += 1
            return _Resp(*script[idx])

        async def close(self):
            self.closed = True

    sess = _Sess()
    fake = types.SimpleNamespace(
        ClientSession=lambda: sess,
        ClientTimeout=lambda **kw: None,
        ClientError=_ClientError,
    )
    monkeypatch.setitem(sys.modules, "aiohttp", fake)
    return sess


@pytest.fixture
def no_sleep(monkeypatch):
    """退避等待归零（只影响进程内 asyncio.sleep，monkeypatch 会自动还原）。"""
    async def _noop(_s):
        return None

    monkeypatch.setattr(api_mod.asyncio, "sleep", _noop)


@pytest.fixture
def sleeps(monkeypatch):
    """记录每次退避的秒数（断言 Retry-After 是否被尊重/夹取）。"""
    delays: list[float] = []

    async def _record(seconds):
        delays.append(seconds)

    monkeypatch.setattr(api_mod.asyncio, "sleep", _record)
    return delays


def _ok() -> tuple[int, str]:
    return (200, '{"Code":0,"Success":true,"Data":{}}')


def test_a_send_is_attempted_exactly_once(monkeypatch):
    """★ 502 是"可能已经转发、只是响应丢了"：发送端点**必须只试一次**。"""
    sess = _install_fake_aiohttp(monkeypatch, [(502, "bad gateway")])
    client = WppClient(base_url="https://vendor.test", authcode="fake", audit=False)
    with pytest.raises(WppApiError) as ei:
        asyncio.run(client.send_text("wxid_a", "hi"))
    assert ei.value.code == "http_502"
    assert sess.calls == 1, "发送端点重试了 —— 可能给对方发了两条"


def test_a_send_retries_once_when_the_gateway_rejects_the_request(monkeypatch, sleeps):
    """★ 503/408/429 = 网关明确"这次没接受" ⇒ 发送端点允许重试**恰好一次**。"""
    sess = _install_fake_aiohttp(monkeypatch, [(503, "busy"), _ok()])
    client = WppClient(base_url="https://vendor.test", authcode="fake", audit=False)
    out = asyncio.run(client.send_text("wxid_a", "hi"))
    assert out.get("Code") == 0
    assert sess.calls == 2
    assert len(sleeps) == 1


@pytest.mark.parametrize("status", [408, 429, 503])
def test_each_safe_status_is_retried_once_for_writes(monkeypatch, no_sleep, status):
    sess = _install_fake_aiohttp(monkeypatch, [(status, "rejected"), (status, "rejected")])
    client = WppClient(base_url="https://vendor.test", authcode="fake", audit=False)
    with pytest.raises(WppApiError) as ei:
        asyncio.run(client.send_text("wxid_a", "hi"))
    assert ei.value.code == f"http_{status}"
    assert sess.calls == 2, "安全状态只该重试一次（总共 2 次请求）"


def test_a_write_never_retries_a_passthrough_error(monkeypatch, no_sleep):
    """★ 网关**透传** pad 的 503（响应带回写头）⇒ 写端点绝不重发。

    这是 v3.1.0 "写端点允许对 503 重试一次" 的边界：503 有两种来源 —— 网关边缘
    （请求没转发，重发安全）与 pad 透传（可能已经把消息发出去了）。只看状态码会把
    后者也重发一遍 ⇒ 对方收到两条微信。判据是网关 pass-through 时回写的
    ``X-Wpp-Token``（边缘自己产生的错误不带它）。
    """
    sess = _install_fake_aiohttp(
        monkeypatch, [(503, "busy", {"X-Wpp-Token": "pub_test_01"}), _ok()])
    client = WppClient(base_url="https://cloud.test/api/v1/gateway", authcode="wxa_test",
                       cloud_mode=True, audit=False, send_allowlist=())
    with pytest.raises(WppApiError) as ei:
        asyncio.run(client.send_text("wxid_a", "hi"))
    assert ei.value.code == "http_503"
    assert sess.calls == 1, "上游已经执行过的 503 被重发了 —— 可能给对方发了两条"


def test_a_write_still_retries_an_edge_rejection(monkeypatch, sleeps):
    """边缘自己拒的 503（没有回写头）= 请求没到 pad ⇒ 写端点仍可重试一次。"""
    sess = _install_fake_aiohttp(monkeypatch, [(503, "degraded"), _ok()])
    client = WppClient(base_url="https://cloud.test/api/v1/gateway", authcode="wxa_test",
                       cloud_mode=True, audit=False, send_allowlist=())
    out = asyncio.run(client.send_text("wxid_a", "hi"))
    assert out.get("Code") == 0
    assert sess.calls == 2
    assert len(sleeps) == 1


def test_the_upstream_marker_is_matched_case_insensitively(monkeypatch, no_sleep):
    """真实 aiohttp 的头是大小写不敏感的 ``CIMultiDict``；普通 dict（小写键）也要认。

    判据写错成精确匹配 ``X-Wpp-Token`` 时，头一到测试替身/代理的重写形态就"看不到"
    ⇒ 透传的 503 被当成边缘拒绝 ⇒ 重发 ⇒ 对方多一条微信。
    """
    sess = _install_fake_aiohttp(
        monkeypatch, [(503, "busy", {"x-wpp-token": "pub_test_01"}), _ok()])
    client = WppClient(base_url="https://cloud.test/api/v1/gateway", authcode="wxa_test",
                       cloud_mode=True, audit=False, send_allowlist=())
    with pytest.raises(WppApiError) as ei:
        asyncio.run(client.send_text("wxid_a", "hi"))
    assert ei.value.code == "http_503"
    assert sess.calls == 1


def test_a_write_never_retries_a_500(monkeypatch, no_sleep):
    """★ 500 可能是"已执行但报错" —— 对写端点绝不重试。"""
    sess = _install_fake_aiohttp(monkeypatch, [(500, "boom"), _ok()])
    client = WppClient(base_url="https://vendor.test", authcode="fake", audit=False)
    with pytest.raises(WppApiError) as ei:
        asyncio.run(client.send_text("wxid_a", "hi"))
    assert ei.value.code == "http_500"
    assert sess.calls == 1


def test_retry_after_seconds_is_honoured(monkeypatch, sleeps):
    sess = _install_fake_aiohttp(
        monkeypatch, [(429, "slow down", {"Retry-After": "1"}), _ok()])
    client = WppClient(base_url="https://vendor.test", authcode="fake", audit=False)
    asyncio.run(client.send_text("wxid_a", "hi"))
    assert sess.calls == 2
    assert sleeps == [1.0]


def test_retry_after_is_clamped_to_ten_seconds(monkeypatch, sleeps):
    sess = _install_fake_aiohttp(
        monkeypatch, [(503, "busy", {"Retry-After": "120"}), _ok()])
    client = WppClient(base_url="https://vendor.test", authcode="fake", audit=False)
    asyncio.run(client.send_text("wxid_a", "hi"))
    assert sleeps == [10.0], "Retry-After 必须夹到 10s 以内，别挂住事件循环"


def test_even_explicit_retries_are_suppressed_for_writes(monkeypatch, no_sleep):
    """★ 通用端点表 handler 走 ``client.call(..., max_retries=2)`` 的默认值；
    收口必须压过调用方显式传的值（否则"记得别重试"又要靠每个调用点自觉）。"""
    sess = _install_fake_aiohttp(monkeypatch, [(502, "bad gateway")])
    client = WppClient(base_url="https://vendor.test", authcode="fake", audit=False)
    with pytest.raises(WppApiError):
        asyncio.run(client.call("/Msg/SendTxt", {"ToWxid": "wxid_a", "Content": "hi"},
                                max_retries=5))
    assert sess.calls == 1


def test_a_read_endpoint_still_retries(monkeypatch, no_sleep):
    """读端点保持原来的自愈能力：503 一次后成功，应发出第 2 次请求。"""
    sess = _install_fake_aiohttp(
        monkeypatch, [(503, "busy"), (200, '{"Code":0,"Success":true,"Data":{}}')])
    client = WppClient(base_url="https://vendor.test", authcode="fake", audit=False)
    out = asyncio.run(client.call("/User/GetContractProfile", {}))
    assert out.get("Code") == 0
    assert sess.calls == 2, "读端点应当重试一次"


def test_the_write_rule_is_in_the_single_entrypoint():
    """判据必须挂在 ``call``（所有业务端点的唯一入口），不是散在各 typed 方法里。"""
    import ast

    src = (api_mod.__file__ or "")
    tree = ast.parse(open(src, encoding="utf-8").read())
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "WppClient")
    fn = next(n for n in cls.body
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "call")
    code = "\n".join(ast.unparse(s) for s in fn.body)
    assert "is_read_only(endpoint)" in code, \
        "call() 里必须按端点分类压掉写端点的重试"
