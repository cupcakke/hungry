from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, AsyncGenerator, Generator
from dataclasses import dataclass
from enum import Enum
import asyncio
import io
import csv
import json
import re
import os
import tempfile

from sqlalchemy import select, update, and_, or_, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from payment_platform.backend.domain.reporting import (
    Report,
    ReportRun,
    ReportTypeModel,
    ReportSchedule,
    ReportDownload,
    SavedQuery,
    QueryResult,
    DataExport,
    ReportStatus,
    ReportType,
    ScheduleFrequency,
    ExportFormat,
    DataExportType,
    DataExportStatus,
)
from payment_platform.shared.exceptions import (
    NotFoundError,
    ValidationError,
    ReportingError,
)
from payment_platform.shared.utils.identifiers import generate_id


REPORT_TYPE_SCHEMAS = {
    ReportType.BALANCE_TRANSACTIONS: {
        "table": "balance_transactions",
        "columns": ["id", "object", "amount", "currency", "status", "description", "created", "available_on"],
        "filters": ["created.gt", "created.lt", "status", "currency", "amount.gt", "amount.lt"],
        "default_sort": "created",
    },
    ReportType.CHARGES: {
        "table": "charges",
        "columns": ["id", "object", "amount", "currency", "status", "description", "created", "customer_id", "paid"],
        "filters": ["created.gt", "created.lt", "status", "currency", "customer", "amount.gt", "amount.lt"],
        "default_sort": "created",
    },
    ReportType.CUSTOMERS: {
        "table": "customers",
        "columns": ["id", "object", "email", "name", "created", "currency", "balance"],
        "filters": ["created.gt", "created.lt", "email", "name"],
        "default_sort": "created",
    },
    ReportType.DISPUTES: {
        "table": "disputes",
        "columns": ["id", "object", "amount", "currency", "status", "reason", "created", "evidence_due_by"],
        "filters": ["created.gt", "created.lt", "status", "currency", "reason"],
        "default_sort": "created",
    },
    ReportType.INVOICES: {
        "table": "invoices",
        "columns": ["id", "object", "amount_due", "currency", "status", "customer_id", "created", "due_date"],
        "filters": ["created.gt", "created.lt", "status", "currency", "customer"],
        "default_sort": "created",
    },
    ReportType.PAYOUTS: {
        "table": "payouts",
        "columns": ["id", "object", "amount", "currency", "status", "arrival_date", "created", "method"],
        "filters": ["created.gt", "created.lt", "status", "currency", "arrival_date"],
        "default_sort": "created",
    },
    ReportType.REFUNDS: {
        "table": "refunds",
        "columns": ["id", "object", "amount", "currency", "status", "reason", "created", "charge_id"],
        "filters": ["created.gt", "created.lt", "status", "currency", "charge"],
        "default_sort": "created",
    },
    ReportType.SUBSCRIPTIONS: {
        "table": "subscriptions",
        "columns": ["id", "object", "status", "current_period_start", "current_period_end", "customer_id", "created"],
        "filters": ["created.gt", "created.lt", "status", "customer"],
        "default_sort": "created",
    },
    ReportType.TAX_RATES: {
        "table": "tax_rates",
        "columns": ["id", "object", "display_name", "percentage", "inclusive", "active", "created"],
        "filters": ["created.gt", "created.lt", "active", "percentage"],
        "default_sort": "created",
    },
}

SAFE_SQL_KEYWORDS = {
    "SELECT", "FROM", "WHERE", "AND", "OR", "ORDER", "BY", "ASC", "DESC",
    "LIMIT", "OFFSET", "AS", "JOIN", "LEFT", "RIGHT", "INNER", "ON",
    "GROUP", "HAVING", "DISTINCT", "NULL", "IS", "NOT", "IN", "LIKE",
    "BETWEEN", "TRUE", "FALSE", "CAST", "COALESCE", "NULLIF",
}

DANGEROUS_PATTERNS = [
    r";\s*DROP",
    r";\s*DELETE",
    r";\s*UPDATE",
    r";\s*INSERT",
    r";\s*ALTER",
    r";\s*CREATE",
    r";\s*TRUNCATE",
    r"--",
    r"/\*",
    r"\*/",
    r"UNION\s+SELECT",
    r"INTO\s+OUTFILE",
    r"LOAD_FILE",
    r"EXEC\s*\(",
    r"EXECUTE\s*\(",
    r"xp_cmdshell",
    r"sp_executesql",
]


@dataclass
class ReportGenerationResult:
    report_id: str
    status: str
    rows_processed: int
    bytes_written: int
    download_url: str
    expires_at: int


@dataclass
class QueryExecutionResult:
    query_id: str
    execution_time_ms: int
    row_count: int
    columns: List[str]
    data: List[Dict[str, Any]]


class ReportService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        account_id: str,
        report_type: str,
        parameters: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Report:
        try:
            report_type_enum = ReportType(report_type)
        except ValueError:
            raise ValidationError(f"Invalid report type: {report_type}", param="report_type")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        expires_at = timestamp + (7 * 24 * 60 * 60)

        report = Report(
            id=self._generate_id("rpt"),
            account_id=account_id,
            report_type=report_type_enum,
            parameters=parameters or {},
            status=ReportStatus.PENDING,
            created_at_timestamp=timestamp,
            expires_at=expires_at,
            metadata_=metadata or {},
        )

        self.session.add(report)
        await self.session.flush()

        return report

    async def generate(self, report_id: str) -> ReportGenerationResult:
        report = await self.get(report_id)
        if not report:
            raise NotFoundError(f"Report {report_id} not found")

        if report.status == ReportStatus.COMPLETED:
            download = await self._get_download(report_id)
            return ReportGenerationResult(
                report_id=report.id,
                status=report.status.value,
                rows_processed=0,
                bytes_written=download.file_size if download else 0,
                download_url=report.download_url or "",
                expires_at=report.expires_at or 0,
            )

        if report.status == ReportStatus.PROCESSING:
            raise ReportingError(
                f"Report {report_id} is already being processed",
                report_id=report_id,
            )

        report.status = ReportStatus.PROCESSING
        await self.session.flush()

        report_run = ReportRun(
            id=self._generate_id("rrun"),
            report_id=report_id,
            started_at=int(datetime.now(timezone.utc).timestamp()),
        )
        self.session.add(report_run)
        await self.session.flush()

        try:
            rows_processed, bytes_written, file_path = await self._generate_report_data(report)

            timestamp = int(datetime.now(timezone.utc).timestamp())
            report.status = ReportStatus.COMPLETED
            report.completed_at = timestamp
            report.download_url = f"/v1/reports/{report_id}/download"

            report_run.completed_at = timestamp
            report_run.rows_processed = rows_processed
            report_run.bytes_written = bytes_written

            download = ReportDownload(
                id=self._generate_id("rdl"),
                report_id=report_id,
                format=ExportFormat.CSV,
                file_path=file_path,
                file_size=bytes_written,
                expires_at=timestamp + (7 * 24 * 60 * 60),
            )
            self.session.add(download)

            await self.session.flush()

            return ReportGenerationResult(
                report_id=report.id,
                status=report.status.value,
                rows_processed=rows_processed,
                bytes_written=bytes_written,
                download_url=report.download_url,
                expires_at=report.expires_at or 0,
            )

        except Exception as e:
            report.status = ReportStatus.FAILED
            report_run.error_message = str(e)
            await self.session.flush()
            raise ReportingError(
                f"Failed to generate report: {str(e)}",
                report_id=report_id,
            )

    async def get(self, report_id: str) -> Optional[Report]:
        query = select(Report).where(Report.id == report_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_status(self, report_id: str) -> Dict[str, Any]:
        report = await self.get(report_id)
        if not report:
            raise NotFoundError(f"Report {report_id} not found")

        report_run_query = select(ReportRun).where(ReportRun.report_id == report_id)
        report_run_result = await self.session.execute(report_run_query)
        report_run = report_run_result.scalar_one_or_none()

        return {
            "report_id": report.id,
            "status": report.status.value,
            "report_type": report.report_type.value,
            "created_at": report.created_at_timestamp,
            "completed_at": report.completed_at,
            "rows_processed": report_run.rows_processed if report_run else 0,
            "bytes_written": report_run.bytes_written if report_run else 0,
            "error_message": report_run.error_message if report_run else None,
        }

    async def download(self, report_id: str, format: str = "csv") -> Tuple[str, bytes, str]:
        report = await self.get(report_id)
        if not report:
            raise NotFoundError(f"Report {report_id} not found")

        if report.status != ReportStatus.COMPLETED:
            raise ReportingError(
                f"Report {report_id} is not ready for download",
                report_id=report_id,
            )

        download = await self._get_download(report_id)
        if not download:
            raise NotFoundError(f"Download for report {report_id} not found")

        current_time = int(datetime.now(timezone.utc).timestamp())
        if download.expires_at < current_time:
            raise ReportingError(
                f"Download for report {report_id} has expired",
                report_id=report_id,
            )

        download.download_count += 1
        await self.session.flush()

        data = await self._read_report_data(download.file_path, format)

        filename = f"report_{report_id}.{format}"
        content_type = self._get_content_type(format)

        return filename, data, content_type

    async def delete(self, report_id: str) -> bool:
        report = await self.get(report_id)
        if not report:
            raise NotFoundError(f"Report {report_id} not found")

        download = await self._get_download(report_id)
        if download:
            await self._delete_report_file(download.file_path)
            await self.session.delete(download)

        await self.session.delete(report)
        await self.session.flush()
        return True

    async def list_reports(
        self,
        account_id: Optional[str] = None,
        report_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[Report]:
        query = select(Report)

        if account_id:
            query = query.where(Report.account_id == account_id)
        if report_type:
            try:
                report_type_enum = ReportType(report_type)
                query = query.where(Report.report_type == report_type_enum)
            except ValueError:
                pass
        if status:
            try:
                status_enum = ReportStatus(status)
                query = query.where(Report.status == status_enum)
            except ValueError:
                pass

        query = query.order_by(Report.created_at_timestamp.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def _generate_report_data(
        self,
        report: Report,
    ) -> Tuple[int, int, str]:
        schema = REPORT_TYPE_SCHEMAS.get(report.report_type)
        if not schema:
            raise ValidationError(f"No schema found for report type: {report.report_type}")

        query = self._build_query(schema, report.parameters)

        result = await self.session.execute(query)
        rows = result.fetchall()

        columns = schema["columns"]

        file_path = tempfile.mktemp(suffix=".csv")
        bytes_written = 0
        rows_processed = 0

        with open(file_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(columns)
            bytes_written += sum(len(str(c)) for c in columns) + len(columns)

            for row in rows:
                row_dict = dict(row._mapping) if hasattr(row, "_mapping") else {}
                csv_row = [row_dict.get(col, "") for col in columns]
                writer.writerow(csv_row)
                bytes_written += sum(len(str(v)) for v in csv_row) + len(csv_row)
                rows_processed += 1

        return rows_processed, bytes_written, file_path

    def _build_query(self, schema: Dict[str, Any], parameters: Dict[str, Any]) -> Select:
        table_name = schema["table"]
        columns = schema["columns"]

        column_exprs = [text(col) for col in columns]
        query = select(*column_exprs).select_from(text(table_name))

        for filter_name, filter_value in parameters.items():
            if filter_name in schema["filters"]:
                query = self._apply_filter(query, filter_name, filter_value)

        sort_column = parameters.get("sort", schema["default_sort"])
        sort_direction = parameters.get("sort_direction", "desc")
        query = query.order_by(text(f"{sort_column} {sort_direction}"))

        limit = parameters.get("limit", 10000)
        query = query.limit(limit)

        return query

    def _apply_filter(self, query: Select, filter_name: str, filter_value: Any) -> Select:
        if filter_name.endswith(".gt"):
            column = filter_name[:-3]
            query = query.where(text(f"{column} > :{column}_gt")).params({f"{column}_gt": filter_value})
        elif filter_name.endswith(".lt"):
            column = filter_name[:-3]
            query = query.where(text(f"{column} < :{column}_lt")).params({f"{column}_lt": filter_value})
        elif filter_name.endswith(".gte"):
            column = filter_name[:-4]
            query = query.where(text(f"{column} >= :{column}_gte")).params({f"{column}_gte": filter_value})
        elif filter_name.endswith(".lte"):
            column = filter_name[:-4]
            query = query.where(text(f"{column} <= :{column}_lte")).params({f"{column}_lte": filter_value})
        else:
            query = query.where(text(f"{filter_name} = :{filter_name}")).params({filter_name: filter_value})

        return query

    async def _get_download(self, report_id: str) -> Optional[ReportDownload]:
        query = select(ReportDownload).where(ReportDownload.report_id == report_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def _read_report_data(self, file_path: str, format: str) -> bytes:
        if format == ExportFormat.CSV.value:
            with open(file_path, "rb") as f:
                return f.read()
        elif format == ExportFormat.JSON.value:
            with open(file_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                data = list(reader)
                return json.dumps(data, indent=2).encode("utf-8")
        elif format == ExportFormat.PARQUET.value:
            with open(file_path, "rb") as f:
                return f.read()
        else:
            with open(file_path, "rb") as f:
                return f.read()

    async def _delete_report_file(self, file_path: str) -> bool:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
            return True
        except Exception:
            return False

    def _get_content_type(self, format: str) -> str:
        content_types = {
            ExportFormat.CSV.value: "text/csv",
            ExportFormat.JSON.value: "application/json",
            ExportFormat.PARQUET.value: "application/octet-stream",
        }
        return content_types.get(format, "application/octet-stream")

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class ReportTypeService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_available(self) -> List[Dict[str, Any]]:
        report_types = []
        for report_type, schema in REPORT_TYPE_SCHEMAS.items():
            report_types.append({
                "id": report_type.value,
                "name": report_type.value.replace("_", " ").title(),
                "columns": schema["columns"],
                "available_filters": schema["filters"],
                "data_source": schema["table"],
                "schedule_support": True,
            })
        return report_types

    async def get_schema(self, report_type: str) -> Dict[str, Any]:
        try:
            report_type_enum = ReportType(report_type)
        except ValueError:
            raise ValidationError(f"Invalid report type: {report_type}", param="report_type")

        schema = REPORT_TYPE_SCHEMAS.get(report_type_enum)
        if not schema:
            raise NotFoundError(f"Schema not found for report type: {report_type}")

        return {
            "id": report_type_enum.value,
            "name": report_type_enum.value.replace("_", " ").title(),
            "columns": schema["columns"],
            "available_filters": schema["filters"],
            "data_source": schema["table"],
            "default_sort": schema["default_sort"],
        }


class ReportScheduleService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        account_id: str,
        report_type: str,
        frequency: str,
        parameters: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ReportSchedule:
        try:
            report_type_enum = ReportType(report_type)
        except ValueError:
            raise ValidationError(f"Invalid report type: {report_type}", param="report_type")

        try:
            frequency_enum = ScheduleFrequency(frequency)
        except ValueError:
            raise ValidationError(f"Invalid frequency: {frequency}", param="frequency")

        timestamp = int(datetime.now(timezone.utc).timestamp())
        next_run_at = self._calculate_next_run(timestamp, frequency_enum)

        schedule = ReportSchedule(
            id=self._generate_id("rsch"),
            account_id=account_id,
            report_type=report_type_enum,
            frequency=frequency_enum,
            parameters=parameters or {},
            next_run_at=next_run_at,
            metadata_=metadata or {},
        )

        self.session.add(schedule)
        await self.session.flush()

        return schedule

    async def update(
        self,
        schedule_id: str,
        frequency: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        active: Optional[bool] = None,
    ) -> ReportSchedule:
        schedule = await self.get(schedule_id)
        if not schedule:
            raise NotFoundError(f"Schedule {schedule_id} not found")

        if frequency:
            try:
                frequency_enum = ScheduleFrequency(frequency)
                schedule.frequency = frequency_enum
                schedule.next_run_at = self._calculate_next_run(
                    int(datetime.now(timezone.utc).timestamp()),
                    frequency_enum,
                )
            except ValueError:
                raise ValidationError(f"Invalid frequency: {frequency}", param="frequency")

        if parameters is not None:
            schedule.parameters = parameters

        if active is not None:
            schedule.active = active

        await self.session.flush()
        return schedule

    async def execute_scheduled(self) -> List[ReportGenerationResult]:
        current_time = int(datetime.now(timezone.utc).timestamp())

        query = select(ReportSchedule).where(
            and_(
                ReportSchedule.active == True,
                ReportSchedule.next_run_at <= current_time,
            )
        )

        result = await self.session.execute(query)
        schedules = list(result.scalars().all())

        results = []
        report_service = ReportService(self.session)

        for schedule in schedules:
            try:
                report = await report_service.create(
                    account_id=schedule.account_id or "",
                    report_type=schedule.report_type.value,
                    parameters=schedule.parameters,
                )

                generation_result = await report_service.generate(report.id)
                results.append(generation_result)

                schedule.last_run_at = current_time
                schedule.next_run_at = self._calculate_next_run(
                    current_time,
                    schedule.frequency,
                )

            except Exception:
                pass

        await self.session.flush()
        return results

    async def get(self, schedule_id: str) -> Optional[ReportSchedule]:
        query = select(ReportSchedule).where(ReportSchedule.id == schedule_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete(self, schedule_id: str) -> bool:
        schedule = await self.get(schedule_id)
        if not schedule:
            raise NotFoundError(f"Schedule {schedule_id} not found")

        await self.session.delete(schedule)
        await self.session.flush()
        return True

    async def list_schedules(
        self,
        account_id: Optional[str] = None,
        active: Optional[bool] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[ReportSchedule]:
        query = select(ReportSchedule)

        if account_id:
            query = query.where(ReportSchedule.account_id == account_id)
        if active is not None:
            query = query.where(ReportSchedule.active == active)

        query = query.order_by(ReportSchedule.next_run_at.asc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    def _calculate_next_run(self, current_time: int, frequency: ScheduleFrequency) -> int:
        if frequency == ScheduleFrequency.DAILY:
            return current_time + (24 * 60 * 60)
        elif frequency == ScheduleFrequency.WEEKLY:
            return current_time + (7 * 24 * 60 * 60)
        elif frequency == ScheduleFrequency.MONTHLY:
            return current_time + (30 * 24 * 60 * 60)
        return current_time + (24 * 60 * 60)

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class QueryService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def execute_query(
        self,
        query_sql: str,
        parameters: Optional[Dict[str, Any]] = None,
        limit: int = 1000,
    ) -> QueryExecutionResult:
        is_valid, error_message = self.validate_query(query_sql)
        if not is_valid:
            raise ValidationError(f"Invalid query: {error_message}", param="query_sql")

        safe_query = self._sanitize_query(query_sql, limit)

        start_time = datetime.now(timezone.utc)

        try:
            if parameters:
                result = await self.session.execute(text(safe_query), parameters)
            else:
                result = await self.session.execute(text(safe_query))
        except Exception as e:
            raise ReportingError(
                f"Query execution failed: {str(e)}",
                query_sql=query_sql,
            )

        end_time = datetime.now(timezone.utc)
        execution_time_ms = int((end_time - start_time).total_seconds() * 1000)

        rows = result.fetchall()
        row_count = len(rows)

        if rows:
            columns = list(rows[0]._mapping.keys()) if hasattr(rows[0], "_mapping") else []
            data = [dict(row._mapping) if hasattr(row, "_mapping") else {} for row in rows]
        else:
            columns = []
            data = []

        return QueryExecutionResult(
            query_id=self._generate_id("qres"),
            execution_time_ms=execution_time_ms,
            row_count=row_count,
            columns=columns,
            data=data,
        )

    def validate_query(self, query_sql: str) -> Tuple[bool, str]:
        query_upper = query_sql.upper().strip()

        if not query_upper.startswith("SELECT"):
            return False, "Only SELECT queries are allowed"

        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, query_upper, re.IGNORECASE):
                return False, f"Potentially dangerous SQL pattern detected: {pattern}"

        for keyword in ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "TRUNCATE"]:
            if re.search(rf"\b{keyword}\b", query_upper):
                return False, f"Dangerous keyword detected: {keyword}"

        return True, ""

    async def save_query(
        self,
        account_id: str,
        name: str,
        query_sql: str,
        parameters: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SavedQuery:
        is_valid, error_message = self.validate_query(query_sql)
        if not is_valid:
            raise ValidationError(f"Invalid query: {error_message}", param="query_sql")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        saved_query = SavedQuery(
            id=self._generate_id("sq"),
            account_id=account_id,
            name=name,
            query_sql=query_sql,
            parameters=parameters,
            created_at_timestamp=timestamp,
            metadata_=metadata or {},
        )

        self.session.add(saved_query)
        await self.session.flush()

        return saved_query

    async def get_saved_query(self, query_id: str) -> Optional[SavedQuery]:
        query = select(SavedQuery).where(SavedQuery.id == query_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_saved_query(self, query_id: str) -> bool:
        saved_query = await self.get_saved_query(query_id)
        if not saved_query:
            raise NotFoundError(f"Saved query {query_id} not found")

        await self.session.delete(saved_query)
        await self.session.flush()
        return True

    async def list_saved_queries(
        self,
        account_id: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[SavedQuery]:
        query = select(SavedQuery)

        if account_id:
            query = query.where(SavedQuery.account_id == account_id)

        query = query.order_by(SavedQuery.created_at_timestamp.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def execute_saved_query(self, query_id: str) -> QueryExecutionResult:
        saved_query = await self.get_saved_query(query_id)
        if not saved_query:
            raise NotFoundError(f"Saved query {query_id} not found")

        result = await self.execute_query(
            saved_query.query_sql,
            saved_query.parameters,
        )

        timestamp = int(datetime.now(timezone.utc).timestamp())
        query_result = QueryResult(
            id=self._generate_id("qr"),
            saved_query_id=query_id,
            execution_time_ms=result.execution_time_ms,
            row_count=result.row_count,
            result_data={"columns": result.columns, "data": result.data[:100]},
            created_at_timestamp=timestamp,
        )

        saved_query.last_run_at = timestamp

        self.session.add(query_result)
        await self.session.flush()

        return result

    def _sanitize_query(self, query_sql: str, limit: int) -> str:
        query = query_sql.strip()
        if not query.endswith(";"):
            query += ";"

        limit_match = re.search(r"\bLIMIT\s+(\d+)", query, re.IGNORECASE)
        if limit_match:
            existing_limit = int(limit_match.group(1))
            if existing_limit > limit:
                query = re.sub(
                    r"\bLIMIT\s+\d+",
                    f"LIMIT {limit}",
                    query,
                    flags=re.IGNORECASE,
                )
        else:
            query = re.sub(r";$", f" LIMIT {limit};", query)

        return query

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class ExportService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_export(
        self,
        account_id: str,
        export_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DataExport:
        try:
            export_type_enum = DataExportType(export_type)
        except ValueError:
            raise ValidationError(f"Invalid export type: {export_type}", param="export_type")

        timestamp = int(datetime.now(timezone.utc).timestamp())

        data_export = DataExport(
            id=self._generate_id("de"),
            account_id=account_id,
            export_type=export_type_enum,
            status=DataExportStatus.PENDING,
            created_at_timestamp=timestamp,
            metadata_=metadata or {},
        )

        self.session.add(data_export)
        await self.session.flush()

        return data_export

    async def prepare_data(self, export_id: str) -> Tuple[str, int]:
        export = await self.get_export(export_id)
        if not export:
            raise NotFoundError(f"Export {export_id} not found")

        export.status = DataExportStatus.PROCESSING
        await self.session.flush()

        try:
            data = await self._collect_export_data(export)

            file_path = tempfile.mktemp(suffix=".json")
            json_data = json.dumps(data, indent=2, default=str)
            bytes_written = len(json_data.encode("utf-8"))

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(json_data)

            timestamp = int(datetime.now(timezone.utc).timestamp())
            export.status = DataExportStatus.COMPLETED
            export.completed_at = timestamp
            export.download_url = f"/v1/data_exports/{export_id}/download"
            export.expires_at = timestamp + (7 * 24 * 60 * 60)

            await self.session.flush()

            return file_path, bytes_written

        except Exception as e:
            export.status = DataExportStatus.FAILED
            await self.session.flush()
            raise ReportingError(
                f"Failed to prepare export: {str(e)}",
                export_id=export_id,
            )

    async def upload_to_storage(self, file_path: str, destination: str) -> str:
        return f"https://storage.example.com/{destination}"

    async def get_export(self, export_id: str) -> Optional[DataExport]:
        query = select(DataExport).where(DataExport.id == export_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_exports(
        self,
        account_id: Optional[str] = None,
        export_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> List[DataExport]:
        query = select(DataExport)

        if account_id:
            query = query.where(DataExport.account_id == account_id)
        if export_type:
            try:
                export_type_enum = DataExportType(export_type)
                query = query.where(DataExport.export_type == export_type_enum)
            except ValueError:
                pass
        if status:
            try:
                status_enum = DataExportStatus(status)
                query = query.where(DataExport.status == status_enum)
            except ValueError:
                pass

        query = query.order_by(DataExport.created_at_timestamp.desc())
        query = query.limit(limit).offset(offset)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def _collect_export_data(self, export: DataExport) -> Dict[str, Any]:
        data = {
            "export_id": export.id,
            "export_type": export.export_type.value,
            "account_id": export.account_id,
            "created_at": export.created_at_timestamp,
        }

        if export.export_type == DataExportType.FULL_ACCOUNT:
            data["customers"] = await self._get_customers(export.account_id)
            data["charges"] = await self._get_charges(export.account_id)
            data["refunds"] = await self._get_refunds(export.account_id)
            data["disputes"] = await self._get_disputes(export.account_id)
        elif export.export_type == DataExportType.PAYMENT_HISTORY:
            data["charges"] = await self._get_charges(export.account_id)
            data["refunds"] = await self._get_refunds(export.account_id)
        elif export.export_type == DataExportType.CUSTOMER_LIST:
            data["customers"] = await self._get_customers(export.account_id)

        return data

    async def _get_customers(self, account_id: str) -> List[Dict[str, Any]]:
        return []

    async def _get_charges(self, account_id: str) -> List[Dict[str, Any]]:
        return []

    async def _get_refunds(self, account_id: str) -> List[Dict[str, Any]]:
        return []

    async def _get_disputes(self, account_id: str) -> List[Dict[str, Any]]:
        return []

    def _generate_id(self, prefix: str) -> str:
        import secrets
        import string
        chars = string.ascii_lowercase + string.digits
        random_part = "".join(secrets.choice(chars) for _ in range(24))
        return f"{prefix}_{random_part}"


class DataAggregationService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def aggregate_payments(
        self,
        account_id: str,
        start_date: int,
        end_date: int,
        group_by: str = "day",
    ) -> List[Dict[str, Any]]:
        query = text("""
            SELECT
                DATE(FROM_UNIXTIME(created)) as date,
                COUNT(*) as payment_count,
                SUM(amount) as total_amount,
                AVG(amount) as avg_amount,
                currency
            FROM charges
            WHERE account_id = :account_id
                AND created >= :start_date
                AND created <= :end_date
            GROUP BY DATE(FROM_UNIXTIME(created)), currency
            ORDER BY date DESC
        """)

        result = await self.session.execute(
            query,
            {"account_id": account_id, "start_date": start_date, "end_date": end_date},
        )

        return [
            {
                "date": row.date,
                "payment_count": row.payment_count,
                "total_amount": row.total_amount,
                "avg_amount": float(row.avg_amount) if row.avg_amount else 0,
                "currency": row.currency,
            }
            for row in result.fetchall()
        ]

    async def aggregate_customers(
        self,
        account_id: str,
        start_date: int,
        end_date: int,
    ) -> Dict[str, Any]:
        query = text("""
            SELECT
                COUNT(*) as total_customers,
                COUNT(CASE WHEN created >= :start_date THEN 1 END) as new_customers
            FROM customers
            WHERE account_id = :account_id
        """)

        result = await self.session.execute(
            query,
            {"account_id": account_id, "start_date": start_date},
        )

        row = result.fetchone()
        if row:
            return {
                "total_customers": row.total_customers,
                "new_customers": row.new_customers,
                "period_start": start_date,
                "period_end": end_date,
            }

        return {
            "total_customers": 0,
            "new_customers": 0,
            "period_start": start_date,
            "period_end": end_date,
        }

    async def calculate_metrics(
        self,
        account_id: str,
        metrics: List[str],
        start_date: int,
        end_date: int,
    ) -> Dict[str, Any]:
        results = {}

        for metric in metrics:
            if metric == "total_volume":
                results["total_volume"] = await self._calculate_total_volume(
                    account_id, start_date, end_date
                )
            elif metric == "average_transaction":
                results["average_transaction"] = await self._calculate_avg_transaction(
                    account_id, start_date, end_date
                )
            elif metric == "success_rate":
                results["success_rate"] = await self._calculate_success_rate(
                    account_id, start_date, end_date
                )
            elif metric == "refund_rate":
                results["refund_rate"] = await self._calculate_refund_rate(
                    account_id, start_date, end_date
                )
            elif metric == "dispute_rate":
                results["dispute_rate"] = await self._calculate_dispute_rate(
                    account_id, start_date, end_date
                )

        return results

    async def _calculate_total_volume(
        self,
        account_id: str,
        start_date: int,
        end_date: int,
    ) -> Dict[str, int]:
        return {"amount": 0, "count": 0}

    async def _calculate_avg_transaction(
        self,
        account_id: str,
        start_date: int,
        end_date: int,
    ) -> int:
        return 0

    async def _calculate_success_rate(
        self,
        account_id: str,
        start_date: int,
        end_date: int,
    ) -> float:
        return 0.0

    async def _calculate_refund_rate(
        self,
        account_id: str,
        start_date: int,
        end_date: int,
    ) -> float:
        return 0.0

    async def _calculate_dispute_rate(
        self,
        account_id: str,
        start_date: int,
        end_date: int,
    ) -> float:
        return 0.0


class CSVExportService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def stream_csv(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        chunk_size: int = 1000,
    ) -> AsyncGenerator[str, None]:
        result = await self.session.execute(text(query), parameters or {})

        rows = result.fetchall()
        if not rows:
            return

        columns = list(rows[0]._mapping.keys()) if hasattr(rows[0], "_mapping") else []
        yield self.format_row(columns) + "\n"

        for i in range(0, len(rows), chunk_size):
            chunk = rows[i:i + chunk_size]
            for row in chunk:
                row_dict = dict(row._mapping) if hasattr(row, "_mapping") else {}
                csv_row = [row_dict.get(col, "") for col in columns]
                yield self.format_row(csv_row) + "\n"

    def format_row(self, row: List[Any]) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(row)
        return output.getvalue().rstrip("\n")

    async def handle_large_datasets(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        output_path: str = None,
        batch_size: int = 10000,
    ) -> Tuple[str, int]:
        if output_path is None:
            output_path = tempfile.mktemp(suffix=".csv")

        result = await self.session.execute(text(query), parameters or {})
        rows = result.fetchall()

        if not rows:
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                pass
            return output_path, 0

        columns = list(rows[0]._mapping.keys()) if hasattr(rows[0], "_mapping") else []
        rows_written = 0
        total_bytes = 0

        with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)

            writer.writerow(columns)
            total_bytes += sum(len(str(c)) for c in columns) + len(columns)

            for row in rows:
                row_dict = dict(row._mapping) if hasattr(row, "_mapping") else {}
                csv_row = [row_dict.get(col, "") for col in columns]
                writer.writerow(csv_row)
                total_bytes += sum(len(str(v)) for v in csv_row) + len(csv_row)
                rows_written += 1

        return output_path, total_bytes

    async def export_to_json(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> str:
        result = await self.session.execute(text(query), parameters or {})
        rows = result.fetchall()

        if not rows:
            return "[]"

        data = [dict(row._mapping) if hasattr(row, "_mapping") else {} for row in rows]
        return json.dumps(data, indent=2, default=str)

    async def export_to_parquet(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        output_path: str = None,
    ) -> str:
        if output_path is None:
            output_path = tempfile.mktemp(suffix=".parquet")

        result = await self.session.execute(text(query), parameters or {})
        rows = result.fetchall()

        data = [dict(row._mapping) if hasattr(row, "_mapping") else {} for row in rows]
        json_data = json.dumps(data, default=str)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(json_data)

        return output_path
