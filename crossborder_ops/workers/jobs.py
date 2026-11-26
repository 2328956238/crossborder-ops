"""APScheduler 任务注册：广告盾巡检（阶段 4）、Insights 同步（阶段 3 能力）。"""
from __future__ import annotations

import logging

from ..db import get_sessionmaker
from ..services import ad_shield_patrol

logger = logging.getLogger(__name__)


async def ad_shield_patrol_job() -> None:
    results = await ad_shield_patrol.patrol_all_shops(get_sessionmaker())
    logger.info("广告盾巡检完成: %s", results)


def register(scheduler) -> None:
    scheduler.register("ad_shield_patrol", ad_shield_patrol_job,
                       trigger="interval", hours=6)
