import os
import sys
from datetime import timedelta
from kombu import Queue, Exchange
from celery import Celery
from celery.schedules import crontab

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from payment_platform.shared.config import settings

celery_app = Celery(
    "payment_platform_worker",
    broker=settings.celery.broker_url,
    backend=settings.celery.result_backend,
)

celery_app.conf.update(
    task_serializer=settings.celery.task_serializer,
    result_serializer=settings.celery.result_serializer,
    accept_content=settings.celery.accept_content,
    timezone=settings.celery.timezone,
    enable_utc=settings.celery.enable_utc,
    task_track_started=settings.celery.task_track_started,
    task_time_limit=settings.celery.task_time_limit,
    task_soft_time_limit=settings.celery.task_soft_time_limit,
    worker_prefetch_multiplier=settings.celery.worker_prefetch_multiplier,
    worker_max_tasks_per_child=settings.celery.worker_max_tasks_per_child,
    task_acks_late=settings.celery.task_acks_late,
    task_reject_on_worker_lost=settings.celery.task_reject_on_worker_lost,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
    task_default_retry_delay=settings.celery.task_default_retry_delay,
    task_max_retries=settings.celery.task_max_retries,
    task_autoretry_for=(Exception,),
    task_retry_backoff=True,
    task_retry_backoff_max=600,
    task_retry_jitter=True,
    task_eager_propagates=False,
    task_send_sent_event=True,
    task_routes={
        "payment_platform.worker_service.tasks.payment_tasks.*": {"queue": "payments"},
        "payment_platform.worker_service.tasks.subscription_tasks.*": {"queue": "subscriptions"},
        "payment_platform.worker_service.tasks.invoice_tasks.*": {"queue": "invoices"},
        "payment_platform.worker_service.tasks.webhook_tasks.*": {"queue": "webhooks"},
        "payment_platform.worker_service.tasks.payout_tasks.*": {"queue": "payouts"},
        "payment_platform.worker_service.tasks.reconciliation_tasks.*": {"queue": "reconciliation"},
        "payment_platform.worker_service.tasks.report_tasks.*": {"queue": "reports"},
        "payment_platform.worker_service.tasks.maintenance_tasks.*": {"queue": "maintenance"},
    },
    task_default_queue="default",
    task_queues=(
        Queue("default", Exchange("default"), routing_key="default"),
        Queue("payments", Exchange("payments"), routing_key="payments.#"),
        Queue("subscriptions", Exchange("subscriptions"), routing_key="subscriptions.#"),
        Queue("invoices", Exchange("invoices"), routing_key="invoices.#"),
        Queue("webhooks", Exchange("webhooks"), routing_key="webhooks.#"),
        Queue("payouts", Exchange("payouts"), routing_key="payouts.#"),
        Queue("reconciliation", Exchange("reconciliation"), routing_key="reconciliation.#"),
        Queue("reports", Exchange("reports"), routing_key="reports.#"),
        Queue("maintenance", Exchange("maintenance"), routing_key="maintenance.#"),
        Queue("dead_letter", Exchange("dead_letter"), routing_key="dead_letter.#"),
    ),
    beat_schedule={
        "process-subscription-billing": {
            "task": "payment_platform.worker_service.tasks.subscription_tasks.process_subscription_billing",
            "schedule": crontab(minute=0, hour="*"),
            "options": {"queue": "subscriptions"},
        },
        "send-subscription-reminders": {
            "task": "payment_platform.worker_service.tasks.subscription_tasks.send_subscription_reminders",
            "schedule": crontab(minute=0, hour=9),
            "options": {"queue": "subscriptions"},
        },
        "retry-failed-webhooks": {
            "task": "payment_platform.worker_service.tasks.webhook_tasks.retry_webhook_delivery",
            "schedule": crontab(minute="*/5"),
            "options": {"queue": "webhooks"},
        },
        "process-webhook-dead-letter": {
            "task": "payment_platform.worker_service.tasks.webhook_tasks.process_webhook_dead_letter",
            "schedule": crontab(minute=0, hour="*/6"),
            "options": {"queue": "webhooks"},
        },
        "reconcile-transactions": {
            "task": "payment_platform.worker_service.tasks.reconciliation_tasks.reconcile_transactions",
            "schedule": crontab(minute=0, hour="*/4"),
            "options": {"queue": "reconciliation"},
        },
        "reconcile-payouts": {
            "task": "payment_platform.worker_service.tasks.reconciliation_tasks.reconcile_payouts",
            "schedule": crontab(minute=0, hour=6),
            "options": {"queue": "reconciliation"},
        },
        "detect-anomalies": {
            "task": "payment_platform.worker_service.tasks.reconciliation_tasks.detect_anomalies",
            "schedule": crontab(minute=0, hour="*/12"),
            "options": {"queue": "reconciliation"},
        },
        "generate-scheduled-reports": {
            "task": "payment_platform.worker_service.tasks.report_tasks.generate_scheduled_reports",
            "schedule": crontab(minute=0, hour=1),
            "options": {"queue": "reports"},
        },
        "cleanup-old-reports": {
            "task": "payment_platform.worker_service.tasks.report_tasks.cleanup_old_reports",
            "schedule": crontab(minute=0, hour=3, day_of_week=0),
            "options": {"queue": "reports"},
        },
        "cleanup-expired-sessions": {
            "task": "payment_platform.worker_service.tasks.maintenance_tasks.cleanup_expired_sessions",
            "schedule": crontab(minute="*/30"),
            "options": {"queue": "maintenance"},
        },
        "archive-old-records": {
            "task": "payment_platform.worker_service.tasks.maintenance_tasks.archive_old_records",
            "schedule": crontab(minute=0, hour=2),
            "options": {"queue": "maintenance"},
        },
        "update-aggregations": {
            "task": "payment_platform.worker_service.tasks.maintenance_tasks.update_aggregations",
            "schedule": crontab(minute=0, hour="*/1"),
            "options": {"queue": "maintenance"},
        },
        "process-smart-retry": {
            "task": "payment_platform.worker_service.tasks.payment_tasks.process_smart_retry",
            "schedule": crontab(minute=0, hour="*/6"),
            "options": {"queue": "payments"},
        },
        "calculate-available-balance": {
            "task": "payment_platform.worker_service.tasks.payout_tasks.calculate_available_balance",
            "schedule": crontab(minute=0, hour="*/1"),
            "options": {"queue": "payouts"},
        },
    },
)

celery_app.autodiscover_tasks([
    "payment_platform.worker_service.tasks.payment_tasks",
    "payment_platform.worker_service.tasks.subscription_tasks",
    "payment_platform.worker_service.tasks.invoice_tasks",
    "payment_platform.worker_service.tasks.webhook_tasks",
    "payment_platform.worker_service.tasks.payout_tasks",
    "payment_platform.worker_service.tasks.reconciliation_tasks",
    "payment_platform.worker_service.tasks.report_tasks",
    "payment_platform.worker_service.tasks.maintenance_tasks",
])
