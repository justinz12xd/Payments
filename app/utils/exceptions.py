"""
Excepciones personalizadas del microservicio de pagos.
"""


class PaymentServiceError(Exception):
    """Error base del servicio de pagos."""
    
    def __init__(self, message: str, code: str = "PAYMENT_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class PaymentNotFoundError(PaymentServiceError):
    """El pago no fue encontrado."""
    
    def __init__(self, payment_id: str):
        super().__init__(
            message=f"Payment not found: {payment_id}",
            code="PAYMENT_NOT_FOUND",
        )
        self.payment_id = payment_id


class PaymentAlreadyProcessedError(PaymentServiceError):
    """El pago ya fue procesado (idempotencia)."""
    
    def __init__(self, idempotency_key: str):
        super().__init__(
            message=f"Payment already processed with idempotency key: {idempotency_key}",
            code="PAYMENT_ALREADY_PROCESSED",
        )
        self.idempotency_key = idempotency_key


class PaymentProviderError(PaymentServiceError):
    """Error del proveedor de pago externo."""
    
    def __init__(self, provider: str, message: str):
        super().__init__(
            message=f"Payment provider error ({provider}): {message}",
            code="PROVIDER_ERROR",
        )
        self.provider = provider


class InvalidPaymentStateError(PaymentServiceError):
    """Operación inválida para el estado actual del pago."""
    
    def __init__(self, payment_id: str, current_state: str, operation: str):
        super().__init__(
            message=f"Cannot {operation} payment {payment_id} in state {current_state}",
            code="INVALID_PAYMENT_STATE",
        )
        self.payment_id = payment_id
        self.current_state = current_state
        self.operation = operation


class WebhookVerificationError(PaymentServiceError):
    """Error de verificación de webhook."""
    
    def __init__(self, message: str):
        super().__init__(
            message=f"Webhook verification failed: {message}",
            code="WEBHOOK_VERIFICATION_FAILED",
        )


class PartnerNotFoundError(PaymentServiceError):
    """El partner no fue encontrado."""
    
    def __init__(self, partner_id: str):
        super().__init__(
            message=f"Partner not found: {partner_id}",
            code="PARTNER_NOT_FOUND",
        )
        self.partner_id = partner_id


class PartnerAlreadyExistsError(PaymentServiceError):
    """El partner ya existe."""
    
    def __init__(self, name: str):
        super().__init__(
            message=f"Partner already exists: {name}",
            code="PARTNER_ALREADY_EXISTS",
        )
        self.name = name


class WebhookDeliveryError(PaymentServiceError):
    """Error al entregar un webhook."""
    
    def __init__(self, partner_name: str, status_code: int | None, message: str):
        super().__init__(
            message=f"Failed to deliver webhook to {partner_name}: {message}",
            code="WEBHOOK_DELIVERY_FAILED",
        )
        self.partner_name = partner_name
        self.status_code = status_code
