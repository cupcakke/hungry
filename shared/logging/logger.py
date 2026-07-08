import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import structlog
from structlog.types import Processor

from payment_platform.shared.config import settings


_context_vars: Dict[str, ContextVar[Optional[str]]] = {
    "request_id": ContextVar("request_id", default=None),
    "user_id": ContextVar("user_id", default=None),
    "account_id": ContextVar("account_id", default=None),
    "session_id": ContextVar("session_id", default=None),
    "correlation_id": ContextVar("correlation_id", default=None),
}


def get_context_var(name: str) -> Optional[str]:
    var = _context_vars.get(name)
    return var.get() if var else None


def set_context_var(name: str, value: str) -> None:
    var = _context_vars.get(name)
    if var:
        var.set(value)


def clear_context_var(name: str) -> None:
    var = _context_vars.get(name)
    if var:
        var.set(None)


def add_context_vars(
    logger: logging.Logger,
    method_name: str,
    event_dict: Dict[str, Any],
) -> Dict[str, Any]:
    for name, var in _context_vars.items():
        value = var.get()
        if value is not None:
            event_dict[name] = value
    return event_dict


def add_timestamp(
    logger: logging.Logger,
    method_name: str,
    event_dict: Dict[str, Any],
) -> Dict[str, Any]:
    event_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
    return event_dict


def add_log_level(
    logger: logging.Logger,
    method_name: str,
    event_dict: Dict[str, Any],
) -> Dict[str, Any]:
    if method_name == "exception":
        event_dict["level"] = "error"
    else:
        event_dict["level"] = method_name.upper()
    return event_dict


def add_service_info(
    logger: logging.Logger,
    method_name: str,
    event_dict: Dict[str, Any],
) -> Dict[str, Any]:
    event_dict["service"] = settings.app_name
    event_dict["version"] = settings.app_version
    event_dict["environment"] = settings.environment.value
    return event_dict


def drop_color_message_key(
    logger: logging.Logger,
    method_name: str,
    event_dict: Dict[str, Any],
) -> Dict[str, Any]:
    event_dict.pop("color_message", None)
    return event_dict


def get_processors() -> list:
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        add_context_vars,
        add_timestamp,
        add_service_info,
    ]
    if settings.observability.logging_format == "json":
        processors.append(structlog.processors.format_exc_info)
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    return processors


def setup_logging() -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.observability.logging_level.value),
    )
    structlog.configure(
        processors=get_processors(),
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: Optional[str] = None) -> structlog.stdlib.BoundLogger:
    if name is None:
        name = settings.app_name
    return structlog.get_logger(name)


class log_context:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.previous_values: Dict[str, Optional[str]] = {}

    def __enter__(self) -> "log_context":
        for key, value in self.kwargs.items():
            self.previous_values[key] = get_context_var(key)
            if value is not None:
                set_context_var(key, str(value))
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        for key in self.kwargs:
            previous_value = self.previous_values.get(key)
            if previous_value is not None:
                set_context_var(key, previous_value)
            else:
                clear_context_var(key)


def bind_context(**kwargs: Any) -> None:
    for key, value in kwargs.items():
        if value is not None:
            set_context_var(key, str(value))


def clear_context() -> None:
    for name in _context_vars:
        clear_context_var(name)


class PaymentLogger:
    def __init__(self, name: Optional[str] = None) -> None:
        self.logger = get_logger(name)

    def debug(self, message: str, **kwargs: Any) -> None:
        self.logger.debug(message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self.logger.info(message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self.logger.warning(message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self.logger.error(message, **kwargs)

    def critical(self, message: str, **kwargs: Any) -> None:
        self.logger.critical(message, **kwargs)

    def exception(self, message: str, **kwargs: Any) -> None:
        self.logger.exception(message, **kwargs)

    def log_payment_event(
        self,
        event_type: str,
        payment_intent_id: str,
        amount: int,
        currency: str,
        status: str,
        **kwargs: Any,
    ) -> None:
        self.info(
            f"Payment event: {event_type}",
            event_type=event_type,
            payment_intent_id=payment_intent_id,
            amount=amount,
            currency=currency,
            status=status,
            **kwargs,
        )

    def log_refund_event(
        self,
        refund_id: str,
        charge_id: str,
        amount: int,
        currency: str,
        status: str,
        **kwargs: Any,
    ) -> None:
        self.info(
            f"Refund event: {refund_id}",
            refund_id=refund_id,
            charge_id=charge_id,
            amount=amount,
            currency=currency,
            status=status,
            **kwargs,
        )

    def log_subscription_event(
        self,
        event_type: str,
        subscription_id: str,
        customer_id: str,
        status: str,
        **kwargs: Any,
    ) -> None:
        self.info(
            f"Subscription event: {event_type}",
            event_type=event_type,
            subscription_id=subscription_id,
            customer_id=customer_id,
            status=status,
            **kwargs,
        )

    def log_webhook_event(
        self,
        event_id: str,
        event_type: str,
        endpoint_id: str,
        status: str,
        **kwargs: Any,
    ) -> None:
        self.info(
            f"Webhook event: {event_type}",
            event_id=event_id,
            event_type=event_type,
            endpoint_id=endpoint_id,
            status=status,
            **kwargs,
        )

    def log_security_event(
        self,
        event_type: str,
        severity: str,
        details: Dict[str, Any],
        **kwargs: Any,
    ) -> None:
        self.warning(
            f"Security event: {event_type}",
            event_type=event_type,
            severity=severity,
            details=details,
            **kwargs,
        )

    def log_audit_event(
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        actor_id: str,
        changes: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        self.info(
            f"Audit event: {action}",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_id=actor_id,
            changes=changes,
            **kwargs,
        )


logger = get_logger()
payment_logger = PaymentLogger("payment_platform")
