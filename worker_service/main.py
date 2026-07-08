import asyncio
import os
import signal
import sys
from typing import Any, Dict, Optional
from datetime import datetime, timezone, timedelta
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from payment_platform.shared.config import settings
from payment_platform.shared.logging import setup_logging, get_logger
from payment_platform.worker_service.celery_app import celery_app
from celery.signals import task_prerun, task_postrun, task_failure

logger = get_logger(__name__)


@task_prerun.connect
def task_prerun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, **extra):
    logger.info(
        "Task starting",
        task_id=task_id,
        task_name=task.name if task else None,
    )


@task_postrun.connect
def task_postrun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, retval=None, state=None, **extra):
    logger.info(
        "Task completed",
        task_id=task_id,
        task_name=task.name if task else None,
        state=state,
    )


@task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, args=None, kwargs=None, traceback=None, **extra):
    logger.error(
        "Task failed",
        task_id=task_id,
        task_name=sender.name if sender else None,
        error=str(exception),
    )


def run_worker():
    setup_logging()
    logger.info("Starting payment platform worker")
    
    celery_app.worker_main(
        argv=[
            "worker",
            "--loglevel=info",
            f"--concurrency={settings.celery.worker_concurrency}",
            "-Q",
            "default,payments,subscriptions,invoices,webhooks,payouts,reconciliation,reports,maintenance",
        ]
    )


def run_beat():
    setup_logging()
    logger.info("Starting payment platform beat scheduler")
    
    celery_app.start(
        argv=[
            "beat",
            "--loglevel=info",
        ]
    )


def run_flower():
    setup_logging()
    logger.info("Starting payment platform flower monitoring")
    
    from celery.bin.flower import flower
    flower().run(
        address="0.0.0.0:5555",
        broker=settings.celery.broker_url,
    )


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Payment Platform Worker Service")
    parser.add_argument(
        "command",
        choices=["worker", "beat", "flower"],
        default="worker",
        help="Service to run (worker, beat, or flower)",
    )
    
    args = parser.parse_args()
    
    if args.command == "worker":
        run_worker()
    elif args.command == "beat":
        run_beat()
    elif args.command == "flower":
        run_flower()
