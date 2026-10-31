"""``hermes send`` / ``send_message`` 的目标解析（纯函数，零第三方依赖）。

## 为什么需要它

Hermes 的 ``tools/send_message_targets.resolve_target_ref`` 对**插件平台**是严格模式：
平台没注册 ``parse_target_ref_fn`` 时，它只认 ``channel_directory.json`` 里的条目，
其余一律报

    Could not resolve 'q123456789' on wechatpadpro. The plugin parser did not recognize it…

只有 cron 投递会带 ``pass_unresolved_references=True``（宽松，原样交给适配器），
于是出现「cron 能发、``hermes send`` 发不了、``send_message`` 发不了」的割裂。
把判据放这里、注册成 ``parse_target_ref_fn``，三条路径就统一了。

## 认哪些形态

微信的联系人/群 id 在这套协议里有三种稳定形态，都是**不可再解析的不透明 id**：

- ``q<数字>``：QQ 绑定的老号，wxid 就是 ``q`` + QQ 号（运营者本人是 ``q123456789``）
- ``wxid_xxx``：新号默认 wxid
- ``<数字>@chatroom``：群

外加两个便利值：``filehelper``（文件传输助手）、``<账号id>:<peer>`` 多账号前缀
（``_standalone_send`` 就按 ``account:peer`` 拆）。**其它一律返回 None**，交给
channel-directory 兜底 —— 宁可报"认不出"，也不要把一个昵称当 wxid 发出去。
"""

from __future__ import annotations

import re

#: 一个账号一个号；多账号时 ``_standalone_send`` 用 ``<account>:<peer>`` 指定发送身份。
_ACCOUNT_PREFIX_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]{0,31}):(.+)$")

#: 单个 peer id 的合法形态。每条都锚定首尾：半截匹配等于猜收件人。
_PEER_PATTERNS = (
    re.compile(r"^q\d{5,12}$"),                       # QQ 号绑定的老 wxid
    re.compile(r"^wxid_[A-Za-z0-9_-]{2,}$"),          # 新号 wxid
    re.compile(r"^\d{3,}@chatroom$"),                 # 群
    re.compile(r"^gh_[A-Za-z0-9_-]{2,}$"),            # 公众号（同名 id 形态）
)

#: 微信内置会话：文件传输助手。发「自己的号」在微信上并不成立，这才是正确目标。
_PEER_ALIASES = frozenset({"filehelper"})


def _is_peer(value: str) -> bool:
    return value in _PEER_ALIASES or any(p.match(value) for p in _PEER_PATTERNS)


def parse_target_ref(target: str) -> tuple[str, str | None] | None:
    """``(chat_id, thread_id)``；认不出返回 ``None``（Hermes 会继续走目录查找）。

    ``chat_id`` 原样返回（含 ``<account>:`` 前缀）——适配器与 standalone sender
    自己按同样的规则拆账号，这里不再做一次归一化，避免两处规则漂移。
    """
    if not isinstance(target, str):
        return None
    ref = target.strip()
    if not ref:
        return None
    if _is_peer(ref):
        return (ref, None)
    prefixed = _ACCOUNT_PREFIX_RE.match(ref)
    if prefixed and _is_peer(prefixed.group(2)):
        return (ref, None)
    return None
