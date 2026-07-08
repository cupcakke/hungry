import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    name: str
    status: HealthStatus
    message: Optional[str] = None
    latency_ms: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class HealthCheck:
    def __init__(
        self,
        name: str,
        check_func: Callable[[], bool],
        timeout_seconds: float = 5.0,
        critical: bool = True,
    ) -> None:
        self.name = name
        self.check_func = check_func
        self.timeout_seconds = timeout_seconds
        self.critical = critical

    async def execute(self) -> HealthCheckResult:
        start_time = time.perf_counter()
        try:
            if asyncio.iscoroutinefunction(self.check_func):
                result = await asyncio.wait_for(
                    self.check_func(),
                    timeout=self.timeout_seconds,
                )
            else:
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, self.check_func),
                    timeout=self.timeout_seconds,
                )
            latency_ms = (time.perf_counter() - start_time) * 1000
            status = HealthStatus.HEALTHY if result else HealthStatus.UNHEALTHY
            return HealthCheckResult(
                name=self.name,
                status=status,
                latency_ms=latency_ms,
            )
        except asyncio.TimeoutError:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Health check timed out after {self.timeout_seconds}s",
                latency_ms=latency_ms,
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            return HealthCheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                latency_ms=latency_ms,
            )


class HealthChecker:
    def __init__(self, service_name: str = "payment_platform") -> None:
        self.service_name = service_name
        self.checks: Dict[str, HealthCheck] = {}
        self._last_results: Dict[str, HealthCheckResult] = {}

    def register_check(
        self,
        name: str,
        check_func: Callable[[], bool],
        timeout_seconds: float = 5.0,
        critical: bool = True,
    ) -> None:
        self.checks[name] = HealthCheck(
            name=name,
            check_func=check_func,
            timeout_seconds=timeout_seconds,
            critical=critical,
        )

    async def run_check(self, name: str) -> HealthCheckResult:
        check = self.checks.get(name)
        if check is None:
            return HealthCheckResult(
                name=name,
                status=HealthStatus.UNKNOWN,
                message="Health check not found",
            )
        result = await check.execute()
        self._last_results[name] = result
        return result

    async def run_all_checks(self) -> Dict[str, HealthCheckResult]:
        results = {}
        tasks = {name: self.run_check(name) for name in self.checks}
        for name, task in tasks.items():
            results[name] = await task
        return results

    async def get_overall_status(self) -> HealthStatus:
        results = await self.run_all_checks()
        has_critical_unhealthy = False
        has_degraded = False
        for name, result in results.items():
            check = self.checks.get(name)
            if check and check.critical and result.status == HealthStatus.UNHEALTHY:
                has_critical_unhealthy = True
            if result.status == HealthStatus.DEGRADED:
                has_degraded = True
        if has_critical_unhealthy:
            return HealthStatus.UNHEALTHY
        if has_degraded:
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY

    async def get_health_report(self) -> Dict[str, Any]:
        results = await self.run_all_checks()
        overall = await self.get_overall_status()
        return {
            "service": self.service_name,
            "status": overall.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": {
                name: {
                    "status": result.status.value,
                    "message": result.message,
                    "latency_ms": result.latency_ms,
                    "details": result.details,
                    "timestamp": result.timestamp,
                }
                for name, result in results.items()
            },
        }

    def get_last_results(self) -> Dict[str, HealthCheckResult]:
        return self._last_results.copy()


health_checker = HealthChecker()


def health_check(
    name: Optional[str] = None,
    timeout_seconds: float = 5.0,
    critical: bool = True,
) -> Callable:
    def decorator(func: Callable) -> Callable:
        check_name = name or func.__name__
        health_checker.register_check(check_name, func, timeout_seconds, critical)
        return func
    return decorator


def check_database_connection() -> bool:
    try:
        from payment_platform.shared.config import settings
        import asyncpg
        import asyncio
        async def _check() -> bool:
            conn = await asyncpg.connect(settings.database.url)
            await conn.execute("SELECT 1")
            await conn.close()
            return True
        loop = asyncio.new_event_loop()
        return loop.run_until_complete(_check())
    except Exception:
        return False


def check_redis_connection() -> bool:
    try:
        import redis
        from payment_platform.shared.config import settings
        client = redis.from_url(settings.redis.url)
        return client.ping()
    except Exception:
        return False


def check_queue_connection() -> bool:
    try:
        from celery import Celery
        from payment_platform.shared.config import settings
        app = Celery(broker=settings.celery.broker_url)
        inspect = app.control.inspect()
        stats = inspect.stats()
        return stats is not None
    except Exception:
        return False


def check_storage_connection() -> bool:
    try:
        from payment_platform.shared.config import settings
        if settings.storage.provider == "local":
            import os
            return os.path.exists(settings.storage.local_path)
        else:
            import boto3
            s3 = boto3.client(
                "s3",
                aws_access_key_id=settings.storage.access_key,
                aws_secret_access_key=settings.storage.secret_key,
                region_name=settings.storage.region,
            )
            s3.head_bucket(Bucket=settings.storage.bucket_name)
            return True
    except Exception:
        return False


def register_default_health_checks() -> None:
    health_checker.register_check("database", check_database_connection)
    health_checker.register_check("redis", check_redis_connection)
    health_checker.register_check("queue", check_queue_connection, critical=False)
    health_checker.register_check("storage", check_storage_connection, critical=False)


class ReadinessChecker:
    def __init__(self) -> None:
        self._ready = False
        self._checks: List[Callable[[], bool]] = []

    def register(self, check: Callable[[], bool]) -> None:
        self._checks.append(check)

    async def is_ready(self) -> bool:
        if not self._ready:
            return False
        for check in self._checks:
            try:
                if not check():
                    return False
            except Exception:
                return False
        return True

    def mark_ready(self) -> None:
        self._ready = True

    def mark_not_ready(self) -> None:
        self._ready = False


readiness_checker = ReadinessChecker()


class LivenessChecker:
    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._last_heartbeat = time.time()

    def heartbeat(self) -> None:
        self._last_heartbeat = time.time()

    def is_alive(self) -> bool:
        return time.time() - self._last_heartbeat < self.timeout_seconds


liveness_checker = LivenessChecker()
