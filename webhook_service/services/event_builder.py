from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypeVar, Generic

from payment_platform.webhook_service.domain.models import (
    EventType,
    WebhookEvent,
)


T = TypeVar("T")


class EventBuilderService:
    API_VERSION = "2024-01-01"

    EVENT_TYPE_MAPPING = {
        "payment_intent": {
            "created": EventType.PAYMENT_INTENT_CREATED,
            "succeeded": EventType.PAYMENT_INTENT_SUCCEEDED,
            "failed": EventType.PAYMENT_INTENT_FAILED,
            "canceled": EventType.PAYMENT_INTENT_CANCELED,
        },
        "charge": {
            "created": EventType.CHARGE_SUCCEEDED,
            "succeeded": EventType.CHARGE_SUCCEEDED,
            "failed": EventType.CHARGE_FAILED,
            "refunded": EventType.CHARGE_REFUNDED,
            "captured": EventType.CHARGE_CAPTURED,
            "dispute_created": EventType.CHARGE_DISPUTE_CREATED,
            "dispute_updated": EventType.CHARGE_DISPUTE_UPDATED,
            "dispute_closed": EventType.CHARGE_DISPUTE_CLOSED,
        },
        "customer": {
            "created": EventType.CUSTOMER_CREATED,
            "updated": EventType.CUSTOMER_UPDATED,
            "deleted": EventType.CUSTOMER_DELETED,
            "source_created": EventType.CUSTOMER_SOURCE_CREATED,
            "source_deleted": EventType.CUSTOMER_SOURCE_DELETED,
            "subscription_created": EventType.SUBSCRIPTION_CREATED,
            "subscription_updated": EventType.SUBSCRIPTION_UPDATED,
            "subscription_deleted": EventType.SUBSCRIPTION_DELETED,
        },
        "invoice": {
            "created": EventType.INVOICE_CREATED,
            "paid": EventType.INVOICE_PAID,
            "payment_succeeded": EventType.INVOICE_PAYMENT_SUCCEEDED,
            "payment_failed": EventType.INVOICE_PAYMENT_FAILED,
        },
        "transfer": {
            "created": EventType.TRANSFER_CREATED,
            "failed": EventType.TRANSFER_FAILED,
        },
        "payout": {
            "created": EventType.PAYOUT_CREATED,
            "succeeded": EventType.PAYOUT_SUCCEEDED,
            "failed": EventType.PAYOUT_FAILED,
        },
        "refund": {
            "created": EventType.REFUND_CREATED,
            "updated": EventType.REFUND_UPDATED,
        },
    }

    def __init__(self):
        self._event_builders: Dict[str, callable] = {}
        self._transformers: Dict[str, callable] = {}

    def build_event(
        self,
        resource_type: str,
        action: str,
        data: Dict[str, Any],
        account_id: Optional[str] = None,
        livemode: bool = False,
        request_id: Optional[str] = None,
    ) -> WebhookEvent:
        event_type = self._resolve_event_type(resource_type, action)
        transformed_data = self.format_payload(resource_type, data)
        event = WebhookEvent(
            type=event_type.value,
            data=transformed_data,
            account_id=account_id,
            livemode=livemode,
            api_version=self.API_VERSION,
            request={"id": request_id} if request_id else None,
        )
        return event

    def _resolve_event_type(self, resource_type: str, action: str) -> EventType:
        resource_mapping = self.EVENT_TYPE_MAPPING.get(resource_type.lower(), {})
        event_type = resource_mapping.get(action.lower())
        if event_type:
            return event_type
        custom_type = f"{resource_type}.{action}"
        for et in EventType:
            if et.value == custom_type:
                return et
        raise ValueError(f"Unknown event type: {resource_type}.{action}")

    def format_payload(
        self,
        resource_type: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        formatted = self._transform_data(data)
        formatted["object"] = resource_type
        return formatted

    def _transform_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        result = {}
        for key, value in data.items():
            if isinstance(value, datetime):
                result[key] = int(value.timestamp())
            elif isinstance(value, dict):
                result[key] = self._transform_data(value)
            elif isinstance(value, list):
                result[key] = [
                    self._transform_data(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value
        return result

    def build_payment_intent_event(
        self,
        payment_intent: Dict[str, Any],
        action: str,
        account_id: Optional[str] = None,
    ) -> WebhookEvent:
        return self.build_event(
            resource_type="payment_intent",
            action=action,
            data=payment_intent,
            account_id=account_id,
        )

    def build_charge_event(
        self,
        charge: Dict[str, Any],
        action: str,
        account_id: Optional[str] = None,
    ) -> WebhookEvent:
        return self.build_event(
            resource_type="charge",
            action=action,
            data=charge,
            account_id=account_id,
        )

    def build_customer_event(
        self,
        customer: Dict[str, Any],
        action: str,
        account_id: Optional[str] = None,
    ) -> WebhookEvent:
        return self.build_event(
            resource_type="customer",
            action=action,
            data=customer,
            account_id=account_id,
        )

    def build_invoice_event(
        self,
        invoice: Dict[str, Any],
        action: str,
        account_id: Optional[str] = None,
    ) -> WebhookEvent:
        return self.build_event(
            resource_type="invoice",
            action=action,
            data=invoice,
            account_id=account_id,
        )

    def build_subscription_event(
        self,
        subscription: Dict[str, Any],
        action: str,
        account_id: Optional[str] = None,
    ) -> WebhookEvent:
        return self.build_event(
            resource_type="customer",
            action=f"subscription_{action}",
            data=subscription,
            account_id=account_id,
        )

    def build_refund_event(
        self,
        refund: Dict[str, Any],
        action: str,
        account_id: Optional[str] = None,
    ) -> WebhookEvent:
        return self.build_event(
            resource_type="refund",
            action=action,
            data=refund,
            account_id=account_id,
        )

    def build_transfer_event(
        self,
        transfer: Dict[str, Any],
        action: str,
        account_id: Optional[str] = None,
    ) -> WebhookEvent:
        return self.build_event(
            resource_type="transfer",
            action=action,
            data=transfer,
            account_id=account_id,
        )

    def build_payout_event(
        self,
        payout: Dict[str, Any],
        action: str,
        account_id: Optional[str] = None,
    ) -> WebhookEvent:
        return self.build_event(
            resource_type="payout",
            action=action,
            data=payout,
            account_id=account_id,
        )

    def build_dispute_event(
        self,
        dispute: Dict[str, Any],
        action: str,
        account_id: Optional[str] = None,
    ) -> WebhookEvent:
        return self.build_event(
            resource_type="charge",
            action=f"dispute_{action}",
            data=dispute,
            account_id=account_id,
        )

    def register_builder(
        self,
        resource_type: str,
        builder: callable,
    ) -> None:
        self._event_builders[resource_type] = builder

    def register_transformer(
        self,
        resource_type: str,
        transformer: callable,
    ) -> None:
        self._transformers[resource_type] = transformer

    def get_supported_event_types(self) -> List[str]:
        types = []
        for resource, actions in self.EVENT_TYPE_MAPPING.items():
            for action, event_type in actions.items():
                types.append(event_type.value)
        return sorted(types)

    def is_event_type_supported(self, event_type: str) -> bool:
        try:
            EventType(event_type)
            return True
        except ValueError:
            return False

    def parse_event_type(self, event_type: str) -> tuple[str, str]:
        parts = event_type.split(".", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return parts[0], "created"
