"""arq worker config. Run: `arq hypha.workers.settings.WorkerSettings`."""

from __future__ import annotations

from arq.connections import RedisSettings

from ..config import get_settings
from .tasks import analyze_task


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    functions = [analyze_task]
    max_jobs = 20
    job_timeout = 60
