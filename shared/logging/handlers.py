import gzip
import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler as BaseRotatingFileHandler
from logging.handlers import SysLogHandler as BaseSysLogHandler
from typing import Any, Dict, List, Optional


class ConsoleHandler(logging.StreamHandler):
    def __init__(self, stream: Any = None, use_colors: bool = True) -> None:
        if stream is None:
            stream = sys.stdout
        super().__init__(stream)
        self.use_colors = use_colors

    def emit(self, record: logging.LogRecord) -> None:
        if self.use_colors:
            record.msg = self._colorize(record)
        super().emit(record)

    def _colorize(self, record: logging.LogRecord) -> str:
        colors = {
            "DEBUG": "\033[36m",
            "INFO": "\033[32m",
            "WARNING": "\033[33m",
            "ERROR": "\033[31m",
            "CRITICAL": "\033[35m",
        }
        reset = "\033[0m"
        color = colors.get(record.levelname, "")
        return f"{color}{record.msg}{reset}"


class FileHandler(logging.FileHandler):
    def __init__(
        self,
        filename: str,
        mode: str = "a",
        encoding: Optional[str] = "utf-8",
        delay: bool = False,
    ) -> None:
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        super().__init__(filename, mode, encoding, delay)


class RotatingFileHandler(BaseRotatingFileHandler):
    def __init__(
        self,
        filename: str,
        mode: str = "a",
        maxBytes: int = 100 * 1024 * 1024,
        backupCount: int = 10,
        encoding: Optional[str] = "utf-8",
        delay: bool = False,
        compress: bool = True,
    ) -> None:
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        self.compress = compress
        super().__init__(filename, mode, maxBytes, backupCount, encoding, delay)

    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
        if self.backupCount > 0:
            for i in range(self.backupCount - 1, 0, -1):
                sfn = self.rotation_filename(f"{self.baseFilename}.{i}")
                dfn = self.rotation_filename(f"{self.baseFilename}.{i + 1}")
                if os.path.exists(sfn):
                    if os.path.exists(dfn):
                        os.remove(dfn)
                    os.rename(sfn, dfn)
            dfn = self.rotation_filename(f"{self.baseFilename}.1")
            if os.path.exists(dfn):
                os.remove(dfn)
            self.rotate(self.baseFilename, dfn)
            if self.compress:
                self._compress_file(dfn)
        if not self.delay:
            self.stream = self._open()

    def _compress_file(self, filepath: str) -> None:
        if os.path.exists(filepath):
            with open(filepath, "rb") as f_in:
                with gzip.open(f"{filepath}.gz", "wb") as f_out:
                    f_out.writelines(f_in)
            os.remove(filepath)


class TimedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    def __init__(
        self,
        filename: str,
        when: str = "midnight",
        interval: int = 1,
        backupCount: int = 30,
        encoding: Optional[str] = "utf-8",
        delay: bool = False,
        utc: bool = True,
        compress: bool = True,
    ) -> None:
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        self.compress = compress
        super().__init__(
            filename,
            when=when,
            interval=interval,
            backupCount=backupCount,
            encoding=encoding,
            delay=delay,
            utc=utc,
        )

    def doRollover(self) -> None:
        super().doRollover()
        if self.compress:
            for i in range(1, self.backupCount + 1):
                sfn = f"{self.baseFilename}.{i}"
                if os.path.exists(sfn) and not sfn.endswith(".gz"):
                    self._compress_file(sfn)

    def _compress_file(self, filepath: str) -> None:
        if os.path.exists(filepath):
            with open(filepath, "rb") as f_in:
                with gzip.open(f"{filepath}.gz", "wb") as f_out:
                    f_out.writelines(f_in)
            os.remove(filepath)


class SysLogHandler(BaseSysLogHandler):
    def __init__(
        self,
        address: tuple = ("localhost", 514),
        facility: int = BaseSysLogHandler.LOG_USER,
        socktype: Any = None,
        ident: str = "payment_platform",
    ) -> None:
        self.ident = ident
        super().__init__(address, facility, socktype)

    def emit(self, record: logging.LogRecord) -> None:
        record.ident = self.ident
        super().emit(record)


class HTTPSHandler(logging.Handler):
    def __init__(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
        batch_size: int = 100,
        batch_timeout: float = 5.0,
    ) -> None:
        super().__init__()
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self._buffer: List[Dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            log_entry = self.format(record)
            if isinstance(log_entry, str):
                import json
                log_entry = json.loads(log_entry)
            self._buffer.append(log_entry)
            if len(self._buffer) >= self.batch_size:
                self._send_batch()
        except Exception:
            self.handleError(record)

    def _send_batch(self) -> None:
        if not self._buffer:
            return
        import httpx
        try:
            response = httpx.post(
                self.url,
                json={"logs": self._buffer},
                headers=self.headers,
                timeout=self.timeout,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"Failed to send logs: {response.status_code}")
            self._buffer.clear()
        except Exception:
            pass

    def close(self) -> None:
        self._send_batch()
        super().close()


class S3Handler(logging.Handler):
    def __init__(
        self,
        bucket: str,
        key_prefix: str = "logs/",
        region: str = "us-east-1",
        batch_size: int = 1000,
        batch_timeout: float = 60.0,
        compress: bool = True,
    ) -> None:
        super().__init__()
        self.bucket = bucket
        self.key_prefix = key_prefix
        self.region = region
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.compress = compress
        self._buffer: List[str] = []
        self._s3_client = None

    def _get_s3_client(self) -> Any:
        if self._s3_client is None:
            import boto3
            self._s3_client = boto3.client("s3", region_name=self.region)
        return self._s3_client

    def emit(self, record: logging.LogRecord) -> None:
        try:
            log_entry = self.format(record)
            self._buffer.append(log_entry)
            if len(self._buffer) >= self.batch_size:
                self._upload_logs()
        except Exception:
            self.handleError(record)

    def _upload_logs(self) -> None:
        if not self._buffer:
            return
        import io
        client = self._get_s3_client()
        timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d/%H%M%S")
        key = f"{self.key_prefix}{timestamp}.json"
        if self.compress:
            key += ".gz"
            buffer = io.BytesIO()
            with gzip.GzipFile(fileobj=buffer, mode="wb") as gz:
                gz.write("\n".join(self._buffer).encode("utf-8"))
            buffer.seek(0)
        else:
            buffer = io.BytesIO("\n".join(self._buffer).encode("utf-8"))
        try:
            client.put_object(Bucket=self.bucket, Key=key, Body=buffer)
            self._buffer.clear()
        except Exception:
            pass

    def close(self) -> None:
        self._upload_logs()
        super().close()


def create_file_handler(
    filename: str,
    max_bytes: int = 100 * 1024 * 1024,
    backup_count: int = 10,
    level: int = logging.DEBUG,
    formatter: Optional[logging.Formatter] = None,
) -> logging.Handler:
    handler = RotatingFileHandler(
        filename=filename,
        maxBytes=max_bytes,
        backupCount=backup_count,
    )
    handler.setLevel(level)
    if formatter:
        handler.setFormatter(formatter)
    return handler


def create_console_handler(
    level: int = logging.INFO,
    use_colors: bool = True,
    formatter: Optional[logging.Formatter] = None,
) -> logging.Handler:
    handler = ConsoleHandler(use_colors=use_colors)
    handler.setLevel(level)
    if formatter:
        handler.setFormatter(formatter)
    return handler


def create_syslog_handler(
    address: tuple = ("localhost", 514),
    facility: int = SysLogHandler.LOG_USER,
    level: int = logging.WARNING,
    formatter: Optional[logging.Formatter] = None,
) -> logging.Handler:
    handler = SysLogHandler(address=address, facility=facility)
    handler.setLevel(level)
    if formatter:
        handler.setFormatter(formatter)
    return handler
