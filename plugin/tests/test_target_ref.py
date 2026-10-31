"""``parse_target_ref_fn`` 的判据测试。

背景：插件平台不注册这个函数时，Hermes 的 ``hermes send`` / ``send_message`` 是严格解析，
只认 channel-directory 条目 —— 运营者的号 ``q123456789`` 这种老 wxid 直接报
"Could not resolve"。这些用例钉住「什么该认、什么必须拒绝」。
"""

from __future__ import annotations

import pytest

from plugin.core.target_ref import parse_target_ref


@pytest.mark.parametrize("ref", [
    "q123456789",            # 运营者本人（QQ 绑定的老 wxid）
    "q12345",
    "wxid_testuser001",
    "wxid_abc",
    "12345678901234567@chatroom",
    "filehelper",
    "gh_abc123",
])
def test_recognizes_wechat_ids(ref):
    assert parse_target_ref(ref) == (ref, None)


@pytest.mark.parametrize("ref", [
    "q123456789",
    "wxid_testuser001",
    "12345678901234567@chatroom",
])
def test_account_prefix_is_preserved(ref):
    """多账号：``<account>:<peer>`` 原样返回，由 standalone sender 拆账号。"""
    target = f"default:{ref}"
    assert parse_target_ref(target) == (target, None)


def test_trims_surrounding_whitespace():
    assert parse_target_ref("  q123456789  ") == ("q123456789", None)


@pytest.mark.parametrize("ref", [
    "",                      # 空
    "   ",
    "接晓银",                 # 昵称不是 id —— 猜收件人比报"认不出"更糟
    "jie_xiao_yin",          # 微信号（alias）不是 wxid
    "139198824",             # 裸数字：既可能是手机号也可能是群，不认
    "wxid_",                 # 半截
    "abc@chatroom",          # 群 id 必须是数字
    "q1391988 24",           # 中间有空格
    "default:",              # 有前缀没 peer
    "default:接晓银",
    None,
    123,
])
def test_rejects_everything_else(ref):
    assert parse_target_ref(ref) is None
