"""Off-hours scheduler (phase 2): APScheduler that triggers drift re-runs in the configured
off-hours window. The single serial worker model means scheduled jobs never overlap a manual
benchmark — they just queue behind it. (The discovery sync job is added in phase 4.)

Run:  uv run python -m daemon.scheduler        # blocks, runs on schedule
Inspect:  uv run python -m daemon.scheduler --list   # print jobs and exit
"""

from __future__ import annotations

import argparse

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from common.config import settings
from daemon.drift_runner import run_drift, use_cases_with_baseline


def drift_all() -> None:
    for uc in use_cases_with_baseline():
        try:
            run_drift(uc)
        except Exception as exc:  # isolate use cases so one failure can't abort the sweep
            print(f"[scheduler] drift error for {uc}: {exc}")


def _parse_offhours() -> tuple[int, int]:
    parts = settings.offhours_start.split(":")
    if len(parts) != 2 or not all(p.strip().isdigit() for p in parts):
        raise ValueError(
            f"offhours_start must be 'HH:MM' (got {settings.offhours_start!r})"
        )
    return int(parts[0]), int(parts[1])


def build_scheduler() -> BlockingScheduler:
    sched = BlockingScheduler(timezone=settings.timezone)
    hour, minute = _parse_offhours()
    sched.add_job(
        drift_all,
        CronTrigger(hour=hour, minute=minute, timezone=settings.timezone),
        id="drift_rerun",
        name="off-hours drift re-runs",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return sched


def main() -> None:
    ap = argparse.ArgumentParser(description="Kelp off-hours scheduler.")
    ap.add_argument("--list", action="store_true", help="print scheduled jobs and exit")
    args = ap.parse_args()

    sched = build_scheduler()
    print(f"Scheduler (tz={settings.timezone}, off-hours start {settings.offhours_start}):")
    for job in sched.get_jobs():
        print(f"  - {job.id}: {job.name} [{job.trigger}]")
    if args.list:
        return
    print("Starting scheduler (Ctrl-C to stop)...")
    sched.start()


if __name__ == "__main__":
    main()
