"""APScheduler 定时任务入口。

阶段 1 只搭骨架：广告盾巡检、Insights 同步等任务分别在阶段 3/4 注册。
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self._scheduler: AsyncIOScheduler | None = None
        self.jobs: list[str] = []

    def start(self) -> None:
        if not self.enabled:
            logger.info("scheduler 未启用（SCHEDULER_ENABLED=false）")
            return
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._scheduler.start()
        logger.info("scheduler 已启动，当前注册任务=%s", self.jobs)

    def register(self, name: str, func, **trigger_kwargs) -> None:
        if self._scheduler is None:
            self.jobs.append(name)
            return
        self._scheduler.add_job(func, id=name, replace_existing=True,
                                misfire_grace_time=60, **trigger_kwargs)
        self.jobs.append(name)

    def shutdown(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
