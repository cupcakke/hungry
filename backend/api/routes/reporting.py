from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Request, HTTPException, Response
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
import io

from payment_platform.backend.infrastructure.database import get_session
from payment_platform.shared.models.pagination import PaginatedResponse
from payment_platform.shared.exceptions import NotFoundError, ValidationError, ReportingError

router = APIRouter()


class ReportCreateRequest(BaseModel):
    report_type: str = Field(..., description="Type of report to generate")
    parameters: Optional[Dict[str, Any]] = Field(default=None, description="Report parameters")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class ReportResponse(BaseModel):
    id: str
    object: str = "report"
    account_id: Optional[str] = None
    report_type: str
    parameters: Optional[Dict[str, Any]] = None
    status: str
    created_at: int
    completed_at: Optional[int] = None
    download_url: Optional[str] = None
    expires_at: Optional[int] = None
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class ReportStatusResponse(BaseModel):
    report_id: str
    status: str
    report_type: str
    created_at: int
    completed_at: Optional[int] = None
    rows_processed: int
    bytes_written: int
    error_message: Optional[str] = None


class ReportTypeResponse(BaseModel):
    id: str
    object: str = "report_type"
    name: str
    columns: List[str] = []
    available_filters: List[str] = []
    data_source: str
    schedule_support: bool = True


class ReportScheduleCreateRequest(BaseModel):
    report_type: str = Field(..., description="Type of report to schedule")
    frequency: str = Field(..., description="Frequency: daily, weekly, or monthly")
    parameters: Optional[Dict[str, Any]] = Field(default=None, description="Report parameters")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class ReportScheduleUpdateRequest(BaseModel):
    frequency: Optional[str] = Field(default=None, description="Frequency: daily, weekly, or monthly")
    parameters: Optional[Dict[str, Any]] = Field(default=None, description="Report parameters")
    active: Optional[bool] = Field(default=None, description="Whether schedule is active")


class ReportScheduleResponse(BaseModel):
    id: str
    object: str = "report_schedule"
    account_id: Optional[str] = None
    report_type: str
    frequency: str
    parameters: Optional[Dict[str, Any]] = None
    next_run_at: int
    last_run_at: Optional[int] = None
    active: bool
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class QueryExecuteRequest(BaseModel):
    query_sql: str = Field(..., description="SQL query to execute")
    parameters: Optional[Dict[str, Any]] = Field(default=None, description="Query parameters")
    limit: Optional[int] = Field(default=1000, description="Maximum rows to return")


class QuerySaveRequest(BaseModel):
    name: str = Field(..., description="Name for the saved query")
    query_sql: str = Field(..., description="SQL query to save")
    parameters: Optional[Dict[str, Any]] = Field(default=None, description="Query parameters")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class SavedQueryResponse(BaseModel):
    id: str
    object: str = "saved_query"
    account_id: Optional[str] = None
    name: str
    query_sql: str
    parameters: Optional[Dict[str, Any]] = None
    created_at: int
    last_run_at: Optional[int] = None
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


class QueryResultResponse(BaseModel):
    id: str
    object: str = "query_result"
    saved_query_id: str
    execution_time_ms: int
    row_count: int
    columns: List[str] = []
    data: List[Dict[str, Any]] = []


class QueryExecutionResponse(BaseModel):
    query_id: str
    execution_time_ms: int
    row_count: int
    columns: List[str] = []
    data: List[Dict[str, Any]] = []


class DataExportCreateRequest(BaseModel):
    export_type: str = Field(..., description="Type of export: full_account, payment_history, or customer_list")
    metadata: Optional[Dict[str, str]] = Field(default=None, description="Metadata key-value pairs")


class DataExportResponse(BaseModel):
    id: str
    object: str = "data_export"
    account_id: Optional[str] = None
    export_type: str
    status: str
    download_url: Optional[str] = None
    created_at: int
    completed_at: Optional[int] = None
    expires_at: Optional[int] = None
    livemode: bool = False
    metadata: Optional[Dict[str, str]] = None


def _get_account_id(request: Request) -> Optional[str]:
    return getattr(request.state, "account_id", None)


def _generate_id(prefix: str) -> str:
    import secrets
    import string
    chars = string.ascii_lowercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(24))
    return f"{prefix}_{random_part}"


def _get_timestamp() -> int:
    import time
    return int(time.time())


@router.post("/reports", response_model=ReportResponse, status_code=201)
async def create_report(
    request: Request,
    data: ReportCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import ReportService
    
    account_id = _get_account_id(request)
    if not account_id:
        raise ValidationError("Account ID is required")
    
    service = ReportService(session)
    report = await service.create(
        account_id=account_id,
        report_type=data.report_type,
        parameters=data.parameters,
        metadata=data.metadata,
    )
    
    return ReportResponse(
        id=report.id,
        account_id=report.account_id,
        report_type=report.report_type.value,
        parameters=report.parameters,
        status=report.status.value,
        created_at=report.created_at_timestamp,
        completed_at=report.completed_at,
        download_url=report.download_url,
        expires_at=report.expires_at,
        metadata=report.metadata_,
    )


@router.get("/reports", response_model=PaginatedResponse[ReportResponse])
async def list_reports(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    report_type: Optional[str] = None,
    status: Optional[str] = None,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import ReportService
    
    account_id = _get_account_id(request)
    service = ReportService(session)
    
    reports = await service.list_reports(
        account_id=account_id,
        report_type=report_type,
        status=status,
        limit=limit + 1,
        offset=0,
    )
    
    has_more = len(reports) > limit
    if has_more:
        reports = reports[:limit]
    
    data = [
        ReportResponse(
            id=r.id,
            account_id=r.account_id,
            report_type=r.report_type.value,
            parameters=r.parameters,
            status=r.status.value,
            created_at=r.created_at_timestamp,
            completed_at=r.completed_at,
            download_url=r.download_url,
            expires_at=r.expires_at,
            metadata=r.metadata_,
        )
        for r in reports
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/reports/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import ReportService
    
    service = ReportService(session)
    report = await service.get(report_id)
    
    if not report:
        raise NotFoundError(f"Report {report_id} not found")
    
    return ReportResponse(
        id=report.id,
        account_id=report.account_id,
        report_type=report.report_type.value,
        parameters=report.parameters,
        status=report.status.value,
        created_at=report.created_at_timestamp,
        completed_at=report.completed_at,
        download_url=report.download_url,
        expires_at=report.expires_at,
        metadata=report.metadata_,
    )


@router.post("/reports/{report_id}/generate", response_model=ReportStatusResponse)
async def generate_report(
    report_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import ReportService
    
    service = ReportService(session)
    result = await service.generate(report_id)
    
    return ReportStatusResponse(
        report_id=result.report_id,
        status=result.status,
        report_type="",
        created_at=0,
        completed_at=0,
        rows_processed=result.rows_processed,
        bytes_written=result.bytes_written,
        error_message=None,
    )


@router.get("/reports/{report_id}/download")
async def download_report(
    report_id: str,
    request: Request,
    format: str = "csv",
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import ReportService
    
    service = ReportService(session)
    filename, data, content_type = await service.download(report_id, format)
    
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.delete("/reports/{report_id}")
async def delete_report(
    report_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import ReportService
    
    service = ReportService(session)
    await service.delete(report_id)
    
    return {"deleted": True, "id": report_id}


@router.get("/report_types", response_model=PaginatedResponse[ReportTypeResponse])
async def list_report_types(
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import ReportTypeService
    
    service = ReportTypeService(session)
    report_types = await service.list_available()
    
    data = [
        ReportTypeResponse(
            id=rt["id"],
            name=rt["name"],
            columns=rt["columns"],
            available_filters=rt["available_filters"],
            data_source=rt["data_source"],
            schedule_support=rt["schedule_support"],
        )
        for rt in report_types
    ]
    
    return PaginatedResponse(data=data, has_more=False)


@router.get("/report_types/{report_type_id}", response_model=ReportTypeResponse)
async def get_report_type(
    report_type_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import ReportTypeService
    
    service = ReportTypeService(session)
    schema = await service.get_schema(report_type_id)
    
    return ReportTypeResponse(
        id=schema["id"],
        name=schema["name"],
        columns=schema["columns"],
        available_filters=schema["available_filters"],
        data_source=schema["data_source"],
        schedule_support=True,
    )


@router.post("/report_schedules", response_model=ReportScheduleResponse, status_code=201)
async def create_report_schedule(
    request: Request,
    data: ReportScheduleCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import ReportScheduleService
    
    account_id = _get_account_id(request)
    if not account_id:
        raise ValidationError("Account ID is required")
    
    service = ReportScheduleService(session)
    schedule = await service.create(
        account_id=account_id,
        report_type=data.report_type,
        frequency=data.frequency,
        parameters=data.parameters,
        metadata=data.metadata,
    )
    
    return ReportScheduleResponse(
        id=schedule.id,
        account_id=schedule.account_id,
        report_type=schedule.report_type.value,
        frequency=schedule.frequency.value,
        parameters=schedule.parameters,
        next_run_at=schedule.next_run_at,
        last_run_at=schedule.last_run_at,
        active=schedule.active,
        metadata=schedule.metadata_,
    )


@router.get("/report_schedules", response_model=PaginatedResponse[ReportScheduleResponse])
async def list_report_schedules(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    active: Optional[bool] = None,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import ReportScheduleService
    
    account_id = _get_account_id(request)
    service = ReportScheduleService(session)
    
    schedules = await service.list_schedules(
        account_id=account_id,
        active=active,
        limit=limit + 1,
        offset=0,
    )
    
    has_more = len(schedules) > limit
    if has_more:
        schedules = schedules[:limit]
    
    data = [
        ReportScheduleResponse(
            id=s.id,
            account_id=s.account_id,
            report_type=s.report_type.value,
            frequency=s.frequency.value,
            parameters=s.parameters,
            next_run_at=s.next_run_at,
            last_run_at=s.last_run_at,
            active=s.active,
            metadata=s.metadata_,
        )
        for s in schedules
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/report_schedules/{schedule_id}", response_model=ReportScheduleResponse)
async def get_report_schedule(
    schedule_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import ReportScheduleService
    
    service = ReportScheduleService(session)
    schedule = await service.get(schedule_id)
    
    if not schedule:
        raise NotFoundError(f"Schedule {schedule_id} not found")
    
    return ReportScheduleResponse(
        id=schedule.id,
        account_id=schedule.account_id,
        report_type=schedule.report_type.value,
        frequency=schedule.frequency.value,
        parameters=schedule.parameters,
        next_run_at=schedule.next_run_at,
        last_run_at=schedule.last_run_at,
        active=schedule.active,
        metadata=schedule.metadata_,
    )


@router.put("/report_schedules/{schedule_id}", response_model=ReportScheduleResponse)
async def update_report_schedule(
    schedule_id: str,
    data: ReportScheduleUpdateRequest,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import ReportScheduleService
    
    service = ReportScheduleService(session)
    schedule = await service.update(
        schedule_id=schedule_id,
        frequency=data.frequency,
        parameters=data.parameters,
        active=data.active,
    )
    
    return ReportScheduleResponse(
        id=schedule.id,
        account_id=schedule.account_id,
        report_type=schedule.report_type.value,
        frequency=schedule.frequency.value,
        parameters=schedule.parameters,
        next_run_at=schedule.next_run_at,
        last_run_at=schedule.last_run_at,
        active=schedule.active,
        metadata=schedule.metadata_,
    )


@router.delete("/report_schedules/{schedule_id}")
async def delete_report_schedule(
    schedule_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import ReportScheduleService
    
    service = ReportScheduleService(session)
    await service.delete(schedule_id)
    
    return {"deleted": True, "id": schedule_id}


@router.post("/queries", response_model=QueryExecutionResponse)
async def execute_query(
    request: Request,
    data: QueryExecuteRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import QueryService
    
    service = QueryService(session)
    result = await service.execute_query(
        query_sql=data.query_sql,
        parameters=data.parameters,
        limit=data.limit or 1000,
    )
    
    return QueryExecutionResponse(
        query_id=result.query_id,
        execution_time_ms=result.execution_time_ms,
        row_count=result.row_count,
        columns=result.columns,
        data=result.data,
    )


@router.get("/queries", response_model=PaginatedResponse[SavedQueryResponse])
async def list_saved_queries(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import QueryService
    
    account_id = _get_account_id(request)
    service = QueryService(session)
    
    queries = await service.list_saved_queries(
        account_id=account_id,
        limit=limit + 1,
        offset=0,
    )
    
    has_more = len(queries) > limit
    if has_more:
        queries = queries[:limit]
    
    data = [
        SavedQueryResponse(
            id=q.id,
            account_id=q.account_id,
            name=q.name,
            query_sql=q.query_sql,
            parameters=q.parameters,
            created_at=q.created_at_timestamp,
            last_run_at=q.last_run_at,
            metadata=q.metadata_,
        )
        for q in queries
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.post("/queries/save", response_model=SavedQueryResponse, status_code=201)
async def save_query(
    request: Request,
    data: QuerySaveRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import QueryService
    
    account_id = _get_account_id(request)
    if not account_id:
        raise ValidationError("Account ID is required")
    
    service = QueryService(session)
    saved_query = await service.save_query(
        account_id=account_id,
        name=data.name,
        query_sql=data.query_sql,
        parameters=data.parameters,
        metadata=data.metadata,
    )
    
    return SavedQueryResponse(
        id=saved_query.id,
        account_id=saved_query.account_id,
        name=saved_query.name,
        query_sql=saved_query.query_sql,
        parameters=saved_query.parameters,
        created_at=saved_query.created_at_timestamp,
        last_run_at=saved_query.last_run_at,
        metadata=saved_query.metadata_,
    )


@router.get("/queries/{query_id}", response_model=SavedQueryResponse)
async def get_saved_query(
    query_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import QueryService
    
    service = QueryService(session)
    saved_query = await service.get_saved_query(query_id)
    
    if not saved_query:
        raise NotFoundError(f"Saved query {query_id} not found")
    
    return SavedQueryResponse(
        id=saved_query.id,
        account_id=saved_query.account_id,
        name=saved_query.name,
        query_sql=saved_query.query_sql,
        parameters=saved_query.parameters,
        created_at=saved_query.created_at_timestamp,
        last_run_at=saved_query.last_run_at,
        metadata=saved_query.metadata_,
    )


@router.post("/queries/{query_id}/execute", response_model=QueryExecutionResponse)
async def execute_saved_query(
    query_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import QueryService
    
    service = QueryService(session)
    result = await service.execute_saved_query(query_id)
    
    return QueryExecutionResponse(
        query_id=result.query_id,
        execution_time_ms=result.execution_time_ms,
        row_count=result.row_count,
        columns=result.columns,
        data=result.data,
    )


@router.delete("/queries/{query_id}")
async def delete_saved_query(
    query_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import QueryService
    
    service = QueryService(session)
    await service.delete_saved_query(query_id)
    
    return {"deleted": True, "id": query_id}


@router.post("/data_exports", response_model=DataExportResponse, status_code=201)
async def create_data_export(
    request: Request,
    data: DataExportCreateRequest,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import ExportService
    
    account_id = _get_account_id(request)
    if not account_id:
        raise ValidationError("Account ID is required")
    
    service = ExportService(session)
    export = await service.create_export(
        account_id=account_id,
        export_type=data.export_type,
        metadata=data.metadata,
    )
    
    return DataExportResponse(
        id=export.id,
        account_id=export.account_id,
        export_type=export.export_type.value,
        status=export.status.value,
        download_url=export.download_url,
        created_at=export.created_at_timestamp,
        completed_at=export.completed_at,
        expires_at=export.expires_at,
        metadata=export.metadata_,
    )


@router.get("/data_exports", response_model=PaginatedResponse[DataExportResponse])
async def list_data_exports(
    request: Request,
    limit: int = 10,
    starting_after: Optional[str] = None,
    export_type: Optional[str] = None,
    status: Optional[str] = None,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import ExportService
    
    account_id = _get_account_id(request)
    service = ExportService(session)
    
    exports = await service.list_exports(
        account_id=account_id,
        export_type=export_type,
        status=status,
        limit=limit + 1,
        offset=0,
    )
    
    has_more = len(exports) > limit
    if has_more:
        exports = exports[:limit]
    
    data = [
        DataExportResponse(
            id=e.id,
            account_id=e.account_id,
            export_type=e.export_type.value,
            status=e.status.value,
            download_url=e.download_url,
            created_at=e.created_at_timestamp,
            completed_at=e.completed_at,
            expires_at=e.expires_at,
            metadata=e.metadata_,
        )
        for e in exports
    ]
    
    return PaginatedResponse(data=data, has_more=has_more)


@router.get("/data_exports/{export_id}", response_model=DataExportResponse)
async def get_data_export(
    export_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import ExportService
    
    service = ExportService(session)
    export = await service.get_export(export_id)
    
    if not export:
        raise NotFoundError(f"Data export {export_id} not found")
    
    return DataExportResponse(
        id=export.id,
        account_id=export.account_id,
        export_type=export.export_type.value,
        status=export.status.value,
        download_url=export.download_url,
        created_at=export.created_at_timestamp,
        completed_at=export.completed_at,
        expires_at=export.expires_at,
        metadata=export.metadata_,
    )


@router.post("/data_exports/{export_id}/prepare")
async def prepare_data_export(
    export_id: str,
    request: Request,
    session = Depends(get_session),
):
    from payment_platform.backend.application.services.reporting_service import ExportService
    
    service = ExportService(session)
    file_path, bytes_written = await service.prepare_data(export_id)
    
    return {
        "export_id": export_id,
        "file_path": file_path,
        "bytes_written": bytes_written,
        "status": "completed",
    }


@router.get("/data_exports/{export_id}/download")
async def download_data_export(
    export_id: str,
    request: Request,
    session = Depends(get_session),
):
    import os
    from payment_platform.backend.application.services.reporting_service import ExportService
    
    service = ExportService(session)
    export = await service.get_export(export_id)
    
    if not export:
        raise NotFoundError(f"Data export {export_id} not found")
    
    if export.status.value != "completed":
        raise ValidationError("Export is not ready for download")
    
    file_path, _ = await service.prepare_data(export_id)
    
    if os.path.exists(file_path):
        with open(file_path, "rb") as f:
            data = f.read()
    else:
        data = b"{}"
    
    return Response(
        content=data,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="export_{export_id}.json"',
        },
    )
