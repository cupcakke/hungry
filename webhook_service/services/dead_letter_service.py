from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from payment_platform.webhook_service.domain.models import (
    DeadLetterEntry,
    WebhookEvent,
)


class DeadLetterService:
    DEFAULT_RETENTION_DAYS = 30
    MAX_ENTRIES_PER_ENDPOINT = 1000

    def __init__(
        self,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        max_entries_per_endpoint: int = MAX_ENTRIES_PER_ENDPOINT,
    ):
        self._retention_days = retention_days
        self._max_entries_per_endpoint = max_entries_per_endpoint
        self._entries: Dict[str, DeadLetterEntry] = {}
        self._entries_by_endpoint: Dict[str, List[str]] = {}
        self._entries_by_event: Dict[str, List[str]] = {}
        self._entries_by_account: Dict[str, List[str]] = {}

    async def store(
        self,
        original_event_id: str,
        original_endpoint_id: str,
        original_payload: Dict[str, Any],
        failure_reason: str,
        failure_count: int = 1,
        account_id: Optional[str] = None,
        last_response_code: Optional[int] = None,
        last_error_message: Optional[str] = None,
    ) -> DeadLetterEntry:
        entry = DeadLetterEntry(
            original_event_id=original_event_id,
            original_endpoint_id=original_endpoint_id,
            original_payload=original_payload,
            failure_reason=failure_reason,
            failure_count=failure_count,
            account_id=account_id,
            last_response_code=last_response_code,
            last_error_message=last_error_message,
            retention_until=datetime.now(timezone.utc) + timedelta(days=self._retention_days),
        )
        await self._apply_retention_limit(original_endpoint_id)
        self._entries[entry.id] = entry
        if original_endpoint_id not in self._entries_by_endpoint:
            self._entries_by_endpoint[original_endpoint_id] = []
        self._entries_by_endpoint[original_endpoint_id].append(entry.id)
        if original_event_id not in self._entries_by_event:
            self._entries_by_event[original_event_id] = []
        self._entries_by_event[original_event_id].append(entry.id)
        if account_id:
            if account_id not in self._entries_by_account:
                self._entries_by_account[account_id] = []
            self._entries_by_account[account_id].append(entry.id)
        return entry

    async def retrieve(self, entry_id: str) -> Optional[DeadLetterEntry]:
        return self._entries.get(entry_id)

    async def retrieve_by_endpoint(
        self,
        endpoint_id: str,
        limit: int = 25,
        offset: int = 0,
    ) -> List[DeadLetterEntry]:
        entry_ids = self._entries_by_endpoint.get(endpoint_id, [])
        paginated_ids = entry_ids[offset:offset + limit]
        entries = []
        for entry_id in paginated_ids:
            entry = self._entries.get(entry_id)
            if entry:
                entries.append(entry)
        entries.sort(key=lambda x: x.created_at, reverse=True)
        return entries

    async def retrieve_by_event(
        self,
        event_id: str,
    ) -> List[DeadLetterEntry]:
        entry_ids = self._entries_by_event.get(event_id, [])
        entries = []
        for entry_id in entry_ids:
            entry = self._entries.get(entry_id)
            if entry:
                entries.append(entry)
        return entries

    async def retrieve_by_account(
        self,
        account_id: str,
        limit: int = 25,
        offset: int = 0,
    ) -> List[DeadLetterEntry]:
        entry_ids = self._entries_by_account.get(account_id, [])
        paginated_ids = entry_ids[offset:offset + limit]
        entries = []
        for entry_id in paginated_ids:
            entry = self._entries.get(entry_id)
            if entry:
                entries.append(entry)
        entries.sort(key=lambda x: x.created_at, reverse=True)
        return entries

    async def replay(
        self,
        entry_id: str,
        new_event_id: Optional[str] = None,
    ) -> Optional[WebhookEvent]:
        entry = await self.retrieve(entry_id)
        if not entry:
            return None
        if entry.replayed:
            return None
        event = WebhookEvent(
            id=new_event_id or f"evt_{uuid4().hex[:24]}",
            type=entry.original_payload.get("type", "unknown"),
            data=entry.original_payload.get("data", entry.original_payload),
            account_id=entry.account_id,
        )
        entry.mark_replayed(event.id)
        return event

    async def replay_batch(
        self,
        entry_ids: List[str],
    ) -> Dict[str, Optional[WebhookEvent]]:
        results = {}
        for entry_id in entry_ids:
            results[entry_id] = await self.replay(entry_id)
        return results

    async def delete(self, entry_id: str) -> bool:
        entry = self._entries.get(entry_id)
        if not entry:
            return False
        if entry.original_endpoint_id in self._entries_by_endpoint:
            self._entries_by_endpoint[entry.original_endpoint_id] = [
                eid for eid in self._entries_by_endpoint[entry.original_endpoint_id]
                if eid != entry_id
            ]
        if entry.original_event_id in self._entries_by_event:
            self._entries_by_event[entry.original_event_id] = [
                eid for eid in self._entries_by_event[entry.original_event_id]
                if eid != entry_id
            ]
        if entry.account_id and entry.account_id in self._entries_by_account:
            self._entries_by_account[entry.account_id] = [
                eid for eid in self._entries_by_account[entry.account_id]
                if eid != entry_id
            ]
        del self._entries[entry_id]
        return True

    async def cleanup_expired(self) -> int:
        now = datetime.now(timezone.utc)
        expired_ids = []
        for entry_id, entry in self._entries.items():
            if entry.retention_until and entry.retention_until < now:
                expired_ids.append(entry_id)
        for entry_id in expired_ids:
            await self.delete(entry_id)
        return len(expired_ids)

    async def _apply_retention_limit(self, endpoint_id: str) -> None:
        entry_ids = self._entries_by_endpoint.get(endpoint_id, [])
        while len(entry_ids) >= self._max_entries_per_endpoint:
            oldest_id = entry_ids.pop(0)
            if oldest_id in self._entries:
                entry = self._entries[oldest_id]
                if entry.original_event_id in self._entries_by_event:
                    self._entries_by_event[entry.original_event_id] = [
                        eid for eid in self._entries_by_event[entry.original_event_id]
                        if eid != oldest_id
                    ]
                if entry.account_id and entry.account_id in self._entries_by_account:
                    self._entries_by_account[entry.account_id] = [
                        eid for eid in self._entries_by_account[entry.account_id]
                        if eid != oldest_id
                    ]
                del self._entries[oldest_id]

    async def get_stats(self) -> Dict[str, Any]:
        total_entries = len(self._entries)
        endpoints_count = len(self._entries_by_endpoint)
        events_count = len(self._entries_by_event)
        accounts_count = len(self._entries_by_account)
        failure_reasons: Dict[str, int] = {}
        for entry in self._entries.values():
            reason = entry.failure_reason
            failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
        return {
            "total_entries": total_entries,
            "endpoints_affected": endpoints_count,
            "unique_events": events_count,
            "accounts_affected": accounts_count,
            "failure_reasons": failure_reasons,
        }

    async def get_endpoint_stats(self, endpoint_id: str) -> Dict[str, Any]:
        entry_ids = self._entries_by_endpoint.get(endpoint_id, [])
        entries = [self._entries[eid] for eid in entry_ids if eid in self._entries]
        total = len(entries)
        if not entries:
            return {
                "endpoint_id": endpoint_id,
                "total_entries": 0,
                "oldest_entry": None,
                "newest_entry": None,
            }
        sorted_entries = sorted(entries, key=lambda x: x.created_at)
        return {
            "endpoint_id": endpoint_id,
            "total_entries": total,
            "oldest_entry": sorted_entries[0].created_at.isoformat(),
            "newest_entry": sorted_entries[-1].created_at.isoformat(),
        }

    def set_retention_policy(self, retention_days: int) -> None:
        if retention_days < 1:
            raise ValueError("Retention days must be at least 1")
        self._retention_days = retention_days

    def set_max_entries_per_endpoint(self, max_entries: int) -> None:
        if max_entries < 1:
            raise ValueError("Max entries must be at least 1")
        self._max_entries_per_endpoint = max_entries
