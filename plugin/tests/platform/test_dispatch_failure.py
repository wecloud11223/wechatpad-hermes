"""兜底派发的**失败可见性**（v3.1.0，对齐 AstrBot v1.2.0 #20）。

## 为什么这条必须单独钉

``SyncFallback`` 判断"本轮能不能推进游标"的唯一信号是 ``on_message`` **有没有抛异常**。
而 ``_dispatch_one`` 传统上是**吞异常**的（聚合器一批 N 条，坏一条只丢那一条）。
两者一组合就是最坏的那种坏法：**兜底以为派发成功了**（游标照走），实际那条消息被
静默丢掉 —— 从这一刻起它既不在厂商游标前、也不在任何人的重试队列里。

这里钉三条：

1. ``_dispatch_one`` **用返回值**报告失败（不靠抛，聚合器路径继续安心吞）；
2. 失败时**释放去重键** —— 不释放的话下一轮重拉扯回来会被 ``_handle_one`` ②
   当成重复消息直接跳过，等于"以为会重试、实际永久丢"；
3. ``_on_sync_raw`` 在**整批派发完之后**才抛，让本轮游标停住（顺序也有判据：
   一条坏消息不许把同批其余条目挡在门外）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from plugin.platform.adapter import WppAdapter


def _adapter() -> WppAdapter:
    a = object.__new__(WppAdapter)
    a._accounts = MagicMock()
    a._pipelines = MagicMock()
    a._dedup = MagicMock()
    return a


def _acct() -> MagicMock:
    acct = MagicMock()
    acct.id = "acct"
    return acct


def _msg(mid: str) -> MagicMock:
    m = MagicMock()
    m.msg_id = mid
    return m


@pytest.mark.asyncio
async def test_a_successful_dispatch_reports_true_and_keeps_the_dedup_key():
    a = _adapter()
    a._handle_one = AsyncMock()
    assert await a._dispatch_one(_acct(), _msg("m1"), MagicMock()) is True
    a._dedup.discard.assert_not_called()


@pytest.mark.asyncio
async def test_a_failed_dispatch_reports_false_and_releases_the_dedup_key():
    """失败必须可被**看见**（返回 False）且**可重放**（释放 msg_id 去重键）。"""
    a = _adapter()
    a._handle_one = AsyncMock(side_effect=RuntimeError("下游炸了"))
    ok = await a._dispatch_one(_acct(), _msg("m1"), MagicMock())
    assert ok is False, "失败被静默吞掉的话，SyncFallback 会照走游标 ⇒ 永久丢消息"
    a._dedup.discard.assert_called_once_with("acct:m1")


@pytest.mark.asyncio
async def test_sync_dispatch_raises_only_after_the_whole_batch_was_tried():
    """一条坏消息不许把同批其余条目挡在门外：**先全部尝试**，再统一报失败。"""
    a = _adapter()
    acct = _acct()
    pipeline = MagicMock()
    pipeline.extract.return_value = [_msg("m1"), _msg("m2"), _msg("m3")]
    a._accounts.get.return_value = acct
    a._pipelines.get.return_value = pipeline
    seen: list[str] = []

    async def _dispatch(_acct_arg, msg, _pipeline):
        seen.append(msg.msg_id)
        return msg.msg_id != "m2"

    a._dispatch_one = _dispatch
    with pytest.raises(RuntimeError, match="1 条"):
        await a._on_sync_raw(acct, {"Data": {}})
    assert seen == ["m1", "m2", "m3"], f"整批都要尝试过才许抛：{seen}"


@pytest.mark.asyncio
async def test_sync_dispatch_stays_quiet_when_every_item_succeeded():
    """全成功时**不许抛** —— 否则每一轮都被当成失败，游标永远不前进。"""
    a = _adapter()
    acct = _acct()
    pipeline = MagicMock()
    pipeline.extract.return_value = [_msg("m1")]
    a._accounts.get.return_value = acct
    a._pipelines.get.return_value = pipeline
    a._dispatch_one = AsyncMock(return_value=True)
    await a._on_sync_raw(acct, {"Data": {}})
