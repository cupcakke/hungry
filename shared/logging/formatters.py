import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict


class JSONFormatter(logging.Formatter):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.default_fields = {
            "service": "payment_platform",
        }

    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        log_data.update(self.default_fields)
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        if hasattr(record, "account_id"):
            log_data["account_id"] = record.account_id
        if hasattr(record, "extra"):
            if isinstance(record.extra, dict):
                log_data.update(record.extra)
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            log_data["stack_trace"] = self.formatStack(record.stack_info)
        return json.dumps(log_data, default=str)


class TextFormatter(logging.Formatter):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        level = record.levelname.ljust(8)
        logger_name = record.name[:30].ljust(30)
        message = record.getMessage()
        base = f"{timestamp} | {level} | {logger_name} | {message}"
        parts = [base]
        if hasattr(record, "request_id") and record.request_id:
            parts.append(f"request_id={record.request_id}")
        if hasattr(record, "user_id") and record.user_id:
            parts.append(f"user_id={record.user_id}")
        if hasattr(record, "account_id") and record.account_id:
            parts.append(f"account_id={record.account_id}")
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            for key, value in record.extra.items():
                parts.append(f"{key}={value}")
        if record.exc_info:
            parts.append(f"\n{self.formatException(record.exc_info)}")
        if record.stack_info:
            parts.append(f"\n{self.formatStack(record.stack_info)}")
        return " | ".join(parts) if len(parts) > 1 else base


class StructuredFormatter(logging.Formatter):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.key_value_separator = "="
        self.field_separator = " "

    def format(self, record: logging.LogRecord) -> str:
        fields = [
            f"timestamp{self.key_value_separator}{datetime.now(timezone.utc).isoformat()}",
            f"level{self.key_value_separator}{record.levelname}",
            f"logger{self.key_value_separator}{record.name}",
            f"module{self.key_value_separator}{record.module}",
            f"function{self.key_value_separator}{record.funcName}",
            f"line{self.key_value_separator}{record.lineno}",
            f"message{self.key_value_separator}{record.getMessage()}",
        ]
        if hasattr(record, "request_id") and record.request_id:
            fields.append(f"request_id{self.key_value_separator}{record.request_id}")
        if hasattr(record, "user_id") and record.user_id:
            fields.append(f"user_id{self.key_value_separator}{record.user_id}")
        if hasattr(record, "account_id") and record.account_id:
            fields.append(f"account_id{self.key_value_separator}{record.account_id}")
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            for key, value in record.extra.items():
                fields.append(f"{key}{self.key_value_separator}{value}")
        if record.exc_info:
            fields.append(f"exception{self.key_value_separator}{self.formatException(record.exc_info)}")
        return self.field_separator.join(fields)


class AuditLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        audit_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": getattr(record, "action", "unknown"),
            "actor_id": getattr(record, "actor_id", None),
            "actor_type": getattr(record, "actor_type", None),
            "resource_type": getattr(record, "resource_type", None),
            "resource_id": getattr(record, "resource_id", None),
            "changes": getattr(record, "changes", None),
            "ip_address": getattr(record, "ip_address", None),
            "user_agent": getattr(record, "user_agent", None),
            "status": getattr(record, "status", "success"),
            "details": getattr(record, "details", {}),
        }
        return json.dumps(audit_data, default=str)


class SecurityLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        security_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": getattr(record, "event_type", "unknown"),
            "severity": getattr(record, "severity", "medium"),
            "source_ip": getattr(record, "source_ip", None),
            "target_resource": getattr(record, "target_resource", None),
            "actor_id": getattr(record, "actor_id", None),
            "outcome": getattr(record, "outcome", "unknown"),
            "details": getattr(record, "details", {}),
        }
        return json.dumps(security_data, default=str)


class PaymentLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payment_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": getattr(record, "event_type", "unknown"),
            "payment_id": getattr(record, "payment_id", None),
            "amount": getattr(record, "amount", None),
            "currency": getattr(record, "currency", None),
            "status": getattr(record, "status", None),
            "customer_id": getattr(record, "customer_id", None),
            "payment_method_id": getattr(record, "payment_method_id", None),
            "error_code": getattr(record, "error_code", None),
            "error_message": getattr(record, "error_message", None),
            "processing_time_ms": getattr(record, "processing_time_ms", None),
        }
        return json.dumps(payment_data, default=str)
