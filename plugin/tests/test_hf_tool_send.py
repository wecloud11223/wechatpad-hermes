"""工具路径发送 → 心流归账（2026-11 修）。

## 修的是什么

心流接管之后，模型是用 ``wpp_quote_reply`` / ``wpp_send_text`` 把话说出去的。
这两条走 ``toolkit/msg.py``，**不经过** ``adapter.send`` —— 而心流的
``_hf_note_sent``（把发送结果翻译成 ``HfSendResult`` 并关窗、记回复状态）只挂在
``adapter.send`` 上。

结果：``begin_pending_send`` 开的窗口没人归账，``expire_stale_judged`` 把**已经发出去**
的回复记成 ``suppressed/no-deliver-outcome``。现场看起来是「这个群整周没说话」，
实际 ``wpp_messages`` 里有出站；更隐蔽的后果是学习闭环拿不到正样本 ⇒ 阈值永远
冻在基线 ⇒ 越跑越安静。

本文件只钉两件事：**成功结果必须回写**（含 vendor 逐条 Ret 判据），且
**归账失败不许把一次已完成的发送翻成失败**。
"""

from __future__ import annotations

import pytest

from plugin.data import repo_messages
from plugin.inbound.heartflow import heartflow as hf
from plugin.toolkit import msg as M


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """落库是附带动作：本套只关心归账参数，不让它真连库。"""
    monkeypatch.setattr(repo_messages, "save_message", lambda *a, **kw: None)


def _capture(monkeypatch) -> list[tuple]:
    seen: list[tuple] = []
    monkeypatch.setattr(hf, "note_sent",
                        lambda *a, **kw: seen.append((a, kw)))
    return seen


def test_note_passes_success_and_message_id(monkeypatch):
    seen = _capture(monkeypatch)
    M._note_hf_tool_send("acct", "g@chatroom", "早", ok=True, msg_id="42")
    assert seen == [(("acct", "g@chatroom", "早"),
                     {"success": True, "message_id": "42"})]


def test_note_swallows_heartflow_failures(monkeypatch):
    """心流模块坏了不能让一次已完成的微信发送变成失败。"""
    monkeypatch.setattr(hf, "note_sent",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("hf down")))
    M._note_hf_tool_send("acct", "g@chatroom", "早", ok=True, msg_id="42")


def test_tool_send_is_reported_to_heartflow(monkeypatch):
    """正常响应 ⇒ ``note_sent(success=True, message_id=<NewMsgId>)``。"""
    seen = _capture(monkeypatch)
    resp = {"Code": 0, "Data": {"BaseResponse": {"ret": 0},
                                "List": [{"Ret": 0, "NewMsgId": 777}]}}
    M._persist_tool_outbound("acct", "g@chatroom", "早", resp)
    assert len(seen) == 1
    args, kw = seen[0]
    assert args[:2] == ("acct", "g@chatroom")
    assert kw["success"] is True
    assert str(kw["message_id"]) == "777"


def test_vendor_rejection_is_not_reported_as_sent(monkeypatch):
    """``Code=0`` 但逐条 ``Ret=-2`` ⇒ 必须报 success=False（与 ``send_ok`` 同一判据）。"""
    seen = _capture(monkeypatch)
    resp = {"Code": 0, "Data": {"BaseResponse": {"ret": 0},
                                "List": [{"Ret": -2, "NewMsgId": 5}]}}
    M._persist_tool_outbound("acct", "g@chatroom", "早", resp)
    assert seen and seen[0][1]["success"] is False
