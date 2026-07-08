from typing import Any, Dict, List, Optional


class PaymentPlatformError(Exception):
    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        http_status: int = 500,
        details: Optional[Dict[str, Any]] = None,
        decline_code: Optional[str] = None,
        param: Optional[str] = None,
        type: Optional[str] = None,
    ):
        self.message = message
        self.code = code or "internal_error"
        self.http_status = http_status
        self.details = details or {}
        self.decline_code = decline_code
        self.param = param
        self.type = type or "api_error"
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "error": {
                "message": self.message,
                "type": self.type,
                "code": self.code,
            }
        }
        if self.decline_code:
            result["error"]["decline_code"] = self.decline_code
        if self.param:
            result["error"]["param"] = self.param
        if self.details:
            result["error"]["details"] = self.details
        return result


class APIError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "An unexpected error occurred.",
        code: str = "api_error",
        http_status: int = 500,
        **kwargs: Any,
    ):
        super().__init__(message=message, code=code, http_status=http_status, type="api_error", **kwargs)


class ConnectionError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Failed to connect to external service.",
        **kwargs: Any,
    ):
        super().__init__(message=message, code="connection_error", http_status=503, type="api_connection_error", **kwargs)


class AuthenticationError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Authentication failed.",
        code: str = "authentication_error",
        **kwargs: Any,
    ):
        super().__init__(message=message, code=code, http_status=401, type="invalid_request_error", **kwargs)


class UnauthorizedError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Unauthorized access.",
        code: str = "unauthorized",
        **kwargs: Any,
    ):
        super().__init__(message=message, code=code, http_status=401, type="invalid_request_error", **kwargs)


class AuthorizationError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "You do not have permission to perform this action.",
        code: str = "authorization_error",
        **kwargs: Any,
    ):
        super().__init__(message=message, code=code, http_status=403, type="invalid_request_error", **kwargs)


class ValidationError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Invalid request parameters.",
        param: Optional[str] = None,
        errors: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ):
        details = {"errors": errors} if errors else {}
        super().__init__(message=message, code="validation_error", http_status=400, param=param, type="invalid_request_error", details=details, **kwargs)


class NotFoundError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "The requested resource was not found.",
        param: Optional[str] = None,
        **kwargs: Any,
    ):
        super().__init__(message=message, code="resource_missing", http_status=404, param=param, type="invalid_request_error", **kwargs)


class ConflictError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "The request conflicts with the current state of the resource.",
        code: str = "resource_conflict",
        **kwargs: Any,
    ):
        super().__init__(message=message, code=code, http_status=409, type="invalid_request_error", **kwargs)


class RateLimitError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Too many requests. Please retry after some time.",
        retry_after: Optional[int] = None,
        **kwargs: Any,
    ):
        details = {"retry_after": retry_after} if retry_after else {}
        super().__init__(message=message, code="rate_limit_error", http_status=429, type="invalid_request_error", details=details, **kwargs)


class ServiceUnavailableError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Service temporarily unavailable. Please retry.",
        **kwargs: Any,
    ):
        super().__init__(message=message, code="service_unavailable", http_status=503, type="api_error", **kwargs)


class IdempotencyError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Idempotency key already used with different parameters.",
        **kwargs: Any,
    ):
        super().__init__(message=message, code="idempotency_error", http_status=400, type="invalid_request_error", **kwargs)


class PaymentError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Payment failed.",
        code: str = "payment_error",
        decline_code: Optional[str] = None,
        payment_intent_id: Optional[str] = None,
        payment_method_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {}
        if payment_intent_id:
            details["payment_intent_id"] = payment_intent_id
        if payment_method_id:
            details["payment_method_id"] = payment_method_id
        super().__init__(message=message, code=code, http_status=402, decline_code=decline_code, type="card_error", details=details, **kwargs)


class CardError(PaymentError):
    def __init__(
        self,
        message: str = "Card error.",
        decline_code: Optional[str] = None,
        **kwargs: Any,
    ):
        super().__init__(message=message, code="card_error", decline_code=decline_code, **kwargs)


class InsufficientFundsError(PaymentError):
    def __init__(
        self,
        message: str = "Insufficient funds.",
        **kwargs: Any,
    ):
        super().__init__(message=message, code="insufficient_funds", decline_code="insufficient_funds", **kwargs)


class CardDeclinedError(PaymentError):
    def __init__(
        self,
        message: str = "Card was declined.",
        decline_code: Optional[str] = "generic_decline",
        **kwargs: Any,
    ):
        super().__init__(message=message, code="card_declined", decline_code=decline_code, **kwargs)


class ExpiredCardError(PaymentError):
    def __init__(
        self,
        message: str = "Card has expired.",
        **kwargs: Any,
    ):
        super().__init__(message=message, code="expired_card", decline_code="expired_card", **kwargs)


class IncorrectCVCError(PaymentError):
    def __init__(
        self,
        message: str = "Incorrect card security code.",
        **kwargs: Any,
    ):
        super().__init__(message=message, code="incorrect_cvc", decline_code="incorrect_cvc", **kwargs)


class IncorrectNumberError(PaymentError):
    def __init__(
        self,
        message: str = "Incorrect card number.",
        **kwargs: Any,
    ):
        super().__init__(message=message, code="incorrect_number", decline_code="incorrect_number", **kwargs)


class ProcessingError(PaymentError):
    def __init__(
        self,
        message: str = "An error occurred while processing the card.",
        **kwargs: Any,
    ):
        super().__init__(message=message, code="processing_error", decline_code="processing_error", **kwargs)


class RefundError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Refund failed.",
        code: str = "refund_error",
        refund_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {"refund_id": refund_id} if refund_id else {}
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", details=details, **kwargs)


class DisputeError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Dispute error.",
        code: str = "dispute_error",
        dispute_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {"dispute_id": dispute_id} if dispute_id else {}
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", details=details, **kwargs)


class SubscriptionError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Subscription error.",
        code: str = "subscription_error",
        subscription_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {"subscription_id": subscription_id} if subscription_id else {}
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", details=details, **kwargs)


class InvoiceError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Invoice error.",
        code: str = "invoice_error",
        invoice_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {"invoice_id": invoice_id} if invoice_id else {}
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", details=details, **kwargs)


class WebhookError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Webhook error.",
        code: str = "webhook_error",
        webhook_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {"webhook_id": webhook_id} if webhook_id else {}
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", details=details, **kwargs)


class WebhookSignatureError(WebhookError):
    def __init__(
        self,
        message: str = "Invalid webhook signature.",
        **kwargs: Any,
    ):
        super().__init__(message=message, code="signature_verification_error", **kwargs)


class WebhookTimeoutError(WebhookError):
    def __init__(
        self,
        message: str = "Webhook delivery timed out.",
        **kwargs: Any,
    ):
        super().__init__(message=message, code="webhook_timeout", http_status=504, **kwargs)


class PayoutError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Payout failed.",
        code: str = "payout_error",
        payout_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {"payout_id": payout_id} if payout_id else {}
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", details=details, **kwargs)


class BalanceError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Balance error.",
        code: str = "balance_error",
        **kwargs: Any,
    ):
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", **kwargs)


class InsufficientBalanceError(BalanceError):
    def __init__(
        self,
        message: str = "Insufficient balance for this operation.",
        available_amount: Optional[int] = None,
        requested_amount: Optional[int] = None,
        currency: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {}
        if available_amount is not None:
            details["available_amount"] = available_amount
        if requested_amount is not None:
            details["requested_amount"] = requested_amount
        if currency:
            details["currency"] = currency
        super().__init__(message=message, code="insufficient_balance", details=details, **kwargs)


class TransferError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Transfer failed.",
        code: str = "transfer_error",
        transfer_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {"transfer_id": transfer_id} if transfer_id else {}
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", details=details, **kwargs)


class CustomerError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Customer error.",
        code: str = "customer_error",
        customer_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {"customer_id": customer_id} if customer_id else {}
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", details=details, **kwargs)


class PaymentMethodError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Payment method error.",
        code: str = "payment_method_error",
        payment_method_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {"payment_method_id": payment_method_id} if payment_method_id else {}
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", details=details, **kwargs)


class CheckoutSessionError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Checkout session error.",
        code: str = "checkout_session_error",
        session_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {"session_id": session_id} if session_id else {}
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", details=details, **kwargs)


class TaxError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Tax calculation error.",
        code: str = "tax_error",
        **kwargs: Any,
    ):
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", **kwargs)


class FraudError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Transaction blocked due to fraud detection.",
        code: str = "fraud_error",
        risk_score: Optional[float] = None,
        rule_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {}
        if risk_score is not None:
            details["risk_score"] = risk_score
        if rule_id:
            details["rule_id"] = rule_id
        super().__init__(message=message, code=code, http_status=403, type="invalid_request_error", details=details, **kwargs)


class PlatformAccountError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Connected account error.",
        code: str = "connected_account_error",
        account_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {"account_id": account_id} if account_id else {}
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", details=details, **kwargs)


class IdentityVerificationError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Identity verification error.",
        code: str = "identity_verification_error",
        verification_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {"verification_id": verification_id} if verification_id else {}
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", details=details, **kwargs)


class CardIssuingError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Card issuing error.",
        code: str = "card_issuing_error",
        card_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {"card_id": card_id} if card_id else {}
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", details=details, **kwargs)


class TreasuryError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Treasury operation error.",
        code: str = "treasury_error",
        financial_account_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {"financial_account_id": financial_account_id} if financial_account_id else {}
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", details=details, **kwargs)


class CapitalError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Capital/financing error.",
        code: str = "capital_error",
        financing_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {"financing_id": financing_id} if financing_id else {}
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", details=details, **kwargs)


class ClimateError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Climate operation error.",
        code: str = "climate_error",
        order_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {"order_id": order_id} if order_id else {}
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", details=details, **kwargs)


class CryptoError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Cryptocurrency payment error.",
        code: str = "crypto_error",
        **kwargs: Any,
    ):
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", **kwargs)


class TerminalError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Terminal error.",
        code: str = "terminal_error",
        reader_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {"reader_id": reader_id} if reader_id else {}
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", details=details, **kwargs)


class ReportError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "Report error.",
        code: str = "report_error",
        report_id: Optional[str] = None,
        **kwargs: Any,
    ):
        details = {"report_id": report_id} if report_id else {}
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", details=details, **kwargs)


class FileUploadError(PaymentPlatformError):
    def __init__(
        self,
        message: str = "File upload error.",
        code: str = "file_upload_error",
        **kwargs: Any,
    ):
        super().__init__(message=message, code=code, http_status=400, type="invalid_request_error", **kwargs)
