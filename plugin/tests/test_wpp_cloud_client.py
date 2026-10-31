"""WPP Cloud 模式的客户端契约（只验 URL/头/边界，不发网络请求）。

WPP 网关与 vendor 直连的差别全在传输面：

* URL 是 ``https://<host>/api/v1/gateway`` + ``/Msg/...``（**不再拼 ``/api``**，
  也不再带 ``?authcode=``）；
* 凭据只走 ``Authorization: Bearer wxa_...``；
* 控制面（Admin/Webhook/Runtime/Customized）与扫码/退出等 Login 接口在本地
  先挡，错误要可直接行动，而不是让网关回 403。
"""

from __future__ import annotations

import pytest

from plugin.core.api_client import WppApiError, WppClient


def _cloud() -> WppClient:
    return WppClient(base_url="https://wpp.test/api/v1/gateway", authcode="wxa_test",
                     account_id="acct", cloud_mode=True, audit=False)


def test_cloud_url_has_no_api_prefix_and_no_authcode_query():
    c = _cloud()
    assert c._raw_url("/Msg/SendTxt") == "https://wpp.test/api/v1/gateway/Msg/SendTxt"
    assert "authcode" not in c._raw_url("/Msg/GetSelfInfo")


def test_cloud_headers_use_bearer_only():
    h = _cloud()._headers()
    assert h["Authorization"] == "Bearer wxa_test"
    assert "X-Access-Token" not in h
    assert "TokenKey" not in h


def test_cloud_blocks_control_plane_and_dangerous_ops():
    c = _cloud()
    for ep in ("/Admin/GetAllUsers", "/Webhook/Set", "/Runtime/Info",
               "/Customized/WXCTDUniftyAuthBatch", "/Tools/SetProxy",
               "/Tools/GetBoundHardDevices", "/Login/GetQR", "/Login/Logout"):
        with pytest.raises(WppApiError) as ei:
            c._raw_url(ep)
        assert ei.value.code == "cloud_blocked", ep


def test_cloud_allows_login_status_and_heartbeat():
    c = _cloud()
    for ep in ("/Login/GetLoginStatus", "/Login/LongLinkStatus",
               "/Login/HeartBeatLong", "/Login/AutoHeartBeat",
               "/Msg/Sync", "/Msg/GetSelfInfo", "/Tools/DownloadImg"):
        assert c._raw_url(ep).startswith("https://wpp.test/api/v1/gateway/"), ep


def test_vendor_mode_is_unchanged():
    c = WppClient(base_url="https://vendor.test", authcode="acct-1",
                  account_id="acct", audit=False)
    url = c._raw_url("/Msg/SendTxt")
    assert url == "https://vendor.test/api/Msg/SendTxt?authcode=acct-1"
    h = c._headers()
    assert h["X-Access-Token"] == "acct-1" and "Authorization" not in h
