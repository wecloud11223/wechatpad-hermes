"""控制台 HTTP 面（``plugin/dashboard/plugin_api.py``）—— 需要 FastAPI。

系统 python 没装 FastAPI 时整体跳过；在 Hermes 运行时里可用：

    uv run --with pytest --with fastapi --with httpx \
        python -m pytest plugin/tests/test_console_api.py -q

只验证**路由契约与安全边界**：凭据不出现、409 结构、降级形状、配对码只返回一次。
真实 DB 行为在 ``test_repo_console`` / ``test_sqlite_backend`` 里测。
"""
from __future__ import annotations

import json
import os
import tempfile
import time

import pytest

pytest.importorskip("fastapi")

_TMP = tempfile.mkdtemp(prefix="wppc-api-")
_ACCOUNTS = os.path.join(_TMP, "accounts")
os.makedirs(_ACCOUNTS, exist_ok=True)

#: 本模块**改写**的两条 env（后端 + sqlite 路径）：整轮测试里不能长期占着，
#: 否则后面 ``test_sqlite_backend`` 会拿到"默认后端 = sqlite"的错误前提。
_OWNED_DB_ENV = ("WECHATPRO_DB_BACKEND", "WECHATPRO_SQLITE_PATH")
_IMPORT_ENV = {k: os.environ.get(k) for k in _OWNED_DB_ENV}

os.environ["WECHATPRO_ACCOUNTS_DIR"] = _ACCOUNTS
os.environ["WECHATPRO_ACCOUNT_BACKUP_DIR"] = os.path.join(_TMP, "backups")
os.environ["WPP_PAIRING_DIR"] = os.path.join(_TMP, "pairing")
os.environ["WECHATPRO_DB_BACKEND"] = "sqlite"
os.environ["WECHATPRO_SQLITE_PATH"] = os.path.join(_TMP, "missing.db")

SECRETS = {
    "authcode": "SECRET-AUTHCODE",
    "tokenKey": "SECRET-TOKEN",
    "webhookSecret": "SECRET-HOOK",
    "webhookPathToken": "SECRET-PATH",
}

_ACCOUNT = {
    "agent": "wpp-wechat-test",
    "enabled": True,
    "nickname": "测试助手",
    "dmPolicy": "allowlist",
    "allowFrom": ["wxid_a"],
    "groupPolicy": "allowlist",
    "groupAllowFrom": ["g1@chatroom"],
    "blacklistGroups": [],
    "heartflow": {"enabled": True, "model": "secret-model", "replyThreshold": 0.6,
                  "whitelistGroups": ["g1@chatroom"]},
    "joinWelcome": {"enabled": True, "mode": "allowlist", "groups": ["g1@chatroom"]},
    **SECRETS,
}


#: 宿主的 ``~/.hermes/.env`` 里有**生产** DB 配置；``plugin_api._preload_env`` 会把它
#: ``setdefault`` 进进程环境（dashboard 进程确实需要，但**测试进程不需要**）。
#: 不隔离的后果实测过：真库用例的门禁被注入 ``WECHATPRO_DB_NAME=wechatpro`` 而变红，
#: ``WECHATPRO_DB_BACKEND`` 还可能被改成 mysql 把默认后端用例带偏。
_SHIELDED_ENV_KEYS = (
    "WECHATPRO_DB_HOST", "WECHATPRO_DB_PORT", "WECHATPRO_DB_NAME",
    "WECHATPRO_DB_USER", "WECHATPRO_DB_PASSWORD", "WECHATPRO_DB_ALLOW_REMOTE",
    "WECHATPRO_DB_CONNECT_TIMEOUT", "WECHATPRO_DB_READ_TIMEOUT",
    "WECHATPRO_DB_WRITE_TIMEOUT",
)


@pytest.fixture(autouse=True)
def _shield_host_db_env(monkeypatch):
    """把宿主 ``.env`` 的生产 DB 键挡在本文件之外，并在用例结束后还原两件事。

    1. ``HERMES_HOME`` 指到临时目录：``_preload_env`` 按 home 找 ``.env``，
       指走之后读不到宿主生产配置（``monkeypatch`` 负责还原）；
    2. ``_preload_env`` 可能已 ``setdefault`` 过 DB 键 —— 记下进入前的值，
       退出时按"原来没有就删掉"还原（``monkeypatch.delenv`` 对不存在的键
       不登记 undo，所以这里手动来）。
    """
    before = {k: os.environ.get(k) for k in _SHIELDED_ENV_KEYS}
    for key in _SHIELDED_ENV_KEYS:
        os.environ.pop(key, None)
    monkeypatch.setenv("HERMES_HOME", _TMP)
    yield
    for key, value in before.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    for key in _OWNED_DB_ENV:
        value = _IMPORT_ENV[key]
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from plugin.dashboard import plugin_api as api

    # conftest 的 autouse 夹具每个用例都会把账号目录指到 tmp_path，
    # 所以这里按**当前**环境变量落文件，而不是模块级常量。
    accounts = os.environ["WECHATPRO_ACCOUNTS_DIR"]
    os.makedirs(accounts, exist_ok=True)
    with open(os.path.join(accounts, "default.json"), "w", encoding="utf-8") as fh:
        json.dump(_ACCOUNT, fh, ensure_ascii=False)

    app = FastAPI()
    app.include_router(api.router, prefix="/api")
    return TestClient(app)


def _assert_no_secrets(payload) -> None:
    blob = json.dumps(payload, ensure_ascii=False)
    for key, value in SECRETS.items():
        assert value not in blob, f"响应泄露了 {key}"
        assert "secret-model" not in blob


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_overview_has_account_statuses_and_no_secrets(client):
    res = client.get("/api/overview")
    assert res.status_code == 200
    body = res.json()
    assert body["selected"] == "default"
    status = body["account_statuses"]["default"]
    for key in ("state", "age_sec", "ws_connected", "config_mtime_ns",
                "last_reload_at", "last_reload_ok"):
        assert key in status
    _assert_no_secrets(body)


def test_diagnostics_exposes_the_cloud_webhook_url_with_the_token_masked(client):
    """v3.1.0：诊断接口给出「WPP 控制台该填的回调地址」，但**路径 token 必须打码**。

    这条字段本来全靠 ``Account.cloud_callback_url`` 现算，现场排障得翻账号配置；
    暴露它的同时把 token 换成 ``mask_secret`` 形式 —— 明文等于泄露回调入口。
    """
    accounts = os.environ["WECHATPRO_ACCOUNTS_DIR"]
    cloud = {
        "agent": "wpp-wechat-test", "enabled": True, "nickname": "云端助手",
        "cloudMode": True,
        "apiBaseUrl": "https://wpp.example.com/api/v1/gateway",
        "gatewayTokenEnv": "WPP_GATEWAY_TOKEN",
        "webhookPublicUrl": "https://plugin.example.com",
        "webhookPath": "/wechatpadpro/default/webhook",
        "webhookPathToken": SECRETS["webhookPathToken"],
    }
    with open(os.path.join(accounts, "default.json"), "w", encoding="utf-8") as fh:
        json.dump(cloud, fh, ensure_ascii=False)

    body = client.get("/api/accounts/default/diagnostics").json()
    url = body["webhook_url"]
    assert url.startswith("https://plugin.example.com/wechatpadpro/"), url
    assert url.endswith("/default/webhook"), url
    assert SECRETS["webhookPathToken"] not in url, "路径 token 不许明文出现"
    assert "SECR...TH" in url, "打码形式应与 mask_secret 一致（留头 4 尾 2）"
    _assert_no_secrets(body)


def test_overview_cloud_account_reports_gateway_not_ws(client):
    accounts = os.environ["WECHATPRO_ACCOUNTS_DIR"]
    cloud = {
        "agent": "wpp-wechat-test", "enabled": True, "nickname": "云端助手",
        "cloudMode": True,
        "apiBaseUrl": "https://wpp.example.com/api/v1/gateway",
        "gatewayTokenEnv": "WPP_GATEWAY_TOKEN",
        "webhookSecretEnv": "WECHATPRO_WEBHOOK_SECRET",
    }
    with open(os.path.join(accounts, "default.json"), "w", encoding="utf-8") as fh:
        json.dump(cloud, fh, ensure_ascii=False)

    body = client.get("/api/overview").json()
    summary = body["accounts"][0]
    assert summary["cloudMode"] is True
    assert summary["transport"] == "cloud_gateway"
    assert body["status"]["cloud_mode"] is True
    status = body["account_statuses"]["default"]
    assert status["cloud_mode"] is True and status["transport"] == "cloud_gateway"
    # 云端账号不再因为「厂商 WS 未连」报警。
    assert not any("WS" in w for w in body["warnings"])
    _assert_no_secrets(body)

    detail = client.get("/api/accounts/default").json()
    assert detail["account"]["cloudMode"] is True
    assert detail["status"]["cloud_mode"] is True
    diag = client.get("/api/accounts/default/diagnostics").json()
    assert diag["credential_presence"].get("gatewayToken") is not None
    assert "authcode" not in diag["credential_presence"]


def test_account_detail_has_heartflow_view_without_credentials(client):
    res = client.get("/api/accounts/default")
    assert res.status_code == 200
    account = res.json()["account"]
    assert account["heartflow"]["replyThreshold"] == 0.6
    assert account["heartflow"]["enabled"] is True
    assert account["advanced"]["mcpEnabled"] is False
    assert isinstance(account["heartflowWarnings"], list)
    _assert_no_secrets(res.json())


def test_policy_put_success_then_mtime_conflict(client):
    detail = client.get("/api/accounts/default").json()["account"]
    expected = detail["config_mtime_ns"]

    ok = client.put("/api/accounts/default/policy",
                    json={"dmPolicy": "open", "expected_mtime_ns": expected})
    assert ok.status_code == 200, ok.text
    assert ok.json()["updated_keys"] == ["dmPolicy"]

    stale = client.put("/api/accounts/default/policy",
                       json={"dmPolicy": "allowlist", "expected_mtime_ns": expected})
    assert stale.status_code == 409
    body = stale.json()["detail"]
    assert body["code"] == "mtime_conflict"
    assert isinstance(body["current_mtime_ns"], int)

    # 坏字段仍是 400，不是 409
    bad = client.put("/api/accounts/default/policy", json={"dmPolicy": "everyone"})
    assert bad.status_code == 400


def test_policy_put_accepts_browser_rounded_mtime(client):
    """浏览器把纳秒 mtime 读成 double 再回传，必须仍能保存（2026-10-27 线上故障）。"""
    expected = client.get("/api/accounts/default").json()["account"]["config_mtime_ns"]
    js_rounded = int(float(expected))
    assert js_rounded != expected

    res = client.put("/api/accounts/default/policy",
                     json={"dmPolicy": "open", "expected_mtime_ns": js_rounded})
    assert res.status_code == 200, res.text
    assert res.json()["updated_keys"] == ["dmPolicy"]


def test_features_put_accepts_advanced_and_debounce(client):
    res = client.put("/api/accounts/default/features",
                     json={"llmIntentEnabled": True, "debounceMs": 750})
    assert res.status_code == 200, res.text
    assert res.json()["updated_keys"] == ["debounceMs", "llmIntentEnabled"]
    bad = client.put("/api/accounts/default/features", json={"debounceMs": 99999})
    assert bad.status_code == 400


def test_group_list_degrades_with_policy_flags(client):
    res = client.get("/api/accounts/default/groups")
    assert res.status_code == 200
    body = res.json()
    # SQLite 文件里没有表 ⇒ 降级但仍是 200
    assert body["db_available"] is False
    assert body["groups"] == []
    _assert_no_secrets(body)


def test_messages_require_a_filter(client):
    res = client.get("/api/accounts/default/messages")
    assert res.status_code == 400
    bad_group = client.get("/api/accounts/default/messages?group_id=not-a-group")
    assert bad_group.status_code == 400
    ok = client.get("/api/accounts/default/messages?group_id=g1@chatroom")
    assert ok.status_code == 200
    assert "messages" in ok.json()
    assert "Cache-Control" in ok.headers


def test_affection_requires_group_id(client):
    assert client.get("/api/accounts/default/affection").status_code == 400
    res = client.get("/api/accounts/default/affection?group_id=g1@chatroom")
    assert res.status_code == 200


def test_heartflow_put_merges_and_returns_warnings(client):
    res = client.put("/api/accounts/default/heartflow",
                     json={"replyThreshold": 0.33})
    assert res.status_code == 200, res.text
    assert res.json()["updated_keys"] == ["heartflow"]
    account = client.get("/api/accounts/default").json()["account"]
    assert account["heartflow"]["replyThreshold"] == 0.33
    assert account["heartflow"]["modelConfigured"] is True


def test_pairing_code_returned_once_and_never_in_get(client):
    created = client.post("/api/accounts/default/pairing")
    assert created.status_code == 200, created.text
    code = created.json()["code"]
    assert code and len(code) == 8

    state = client.get("/api/accounts/default/pairing")
    assert state.status_code == 200
    assert "code" not in state.json()

    removed = client.delete("/api/accounts/default/pairing/wxid_nobody")
    assert removed.status_code == 200
    assert removed.json()["removed"] is False
    assert code not in json.dumps(removed.json(), ensure_ascii=False)


def test_reload_bumps_mtime_without_touching_content(client):
    path = os.path.join(os.environ["WECHATPRO_ACCOUNTS_DIR"], "default.json")
    before_bytes = open(path, "rb").read()
    before_ns = os.stat(path).st_mtime_ns
    res = client.post("/api/accounts/default/reload")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["mtime_ns"] > before_ns
    assert open(path, "rb").read() == before_bytes


def test_unknown_account_is_404(client):
    assert client.get("/api/accounts/nope").status_code == 404
    assert client.post("/api/accounts/nope/reload").status_code == 404


def test_diagnostics_never_leaks_env_values(client):
    res = client.get("/api/accounts/default/diagnostics")
    assert res.status_code == 200
    body = res.json()
    assert set(body["env"]["presence"]) >= {"api_base", "authcode", "token_key"}
    assert all(isinstance(v, bool) for v in body["env"]["presence"].values())
    assert isinstance(body["checks"], list) and body["checks"]
    _assert_no_secrets(body)


def test_style_and_insights_routes_degrade_cleanly(client):
    for path in ("/api/accounts/default/style-cards",
                 "/api/accounts/default/groups/g1@chatroom/insights",
                 "/api/accounts/default/analytics?hours=24"):
        res = client.get(path)
        assert res.status_code == 200, (path, res.text)
        assert res.json()["ok"] is True
