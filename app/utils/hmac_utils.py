"""
Utilidades para firmas HMAC-SHA256.
Usadas para firmar y verificar webhooks B2B.
"""

import hashlib
import hmac
import time
from typing import Tuple

import structlog


logger = structlog.get_logger(__name__)

# Tolerancia de tiempo para verificar webhooks (5 minutos)
TIMESTAMP_TOLERANCE_SECONDS = 300


def generate_signature(payload: bytes, secret: str) -> str:
    """
    Genera una firma HMAC-SHA256 para un payload.
    
    Args:
        payload: Datos a firmar (bytes)
        secret: Clave secreta
        
    Returns:
        Firma hexadecimal
    """
    return hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()


def verify_signature(
    payload: bytes,
    signature: str,
    secret: str,
) -> bool:
    """
    Verifica una firma HMAC-SHA256.
    
    Args:
        payload: Datos firmados (bytes)
        signature: Firma a verificar
        secret: Clave secreta
        
    Returns:
        True si la firma es válida
    """
    expected = generate_signature(payload, secret)
    
    # DEBUG: Log detallado de la verificación
    logger.debug(
        "Signature verification",
        payload_length=len(payload),
        payload_preview=payload[:100].decode('utf-8', errors='ignore') if len(payload) > 0 else "",
        secret_prefix=secret[:10] if secret else "None",
        received_signature=signature,
        expected_signature=expected,
        match=expected == signature,
    )
    
    return hmac.compare_digest(expected, signature)


def create_webhook_signature_header(
    payload: bytes,
    secret: str,
    timestamp: int | None = None,
) -> str:
    """
    Crea el header de firma para un webhook saliente.
    
    Formato: "t=<timestamp>,v1=<signature>"
    
    La firma se calcula sobre: "<timestamp>.<payload>"
    Esto previene ataques de replay.
    
    Args:
        payload: Cuerpo del webhook (bytes)
        secret: Clave secreta del partner
        timestamp: Unix timestamp (usa tiempo actual si no se proporciona)
        
    Returns:
        Header de firma
    """
    if timestamp is None:
        timestamp = int(time.time())
    
    # Crear el mensaje a firmar: timestamp.payload
    signed_payload = f"{timestamp}.".encode("utf-8") + payload
    
    signature = generate_signature(signed_payload, secret)
    
    return f"t={timestamp},v1={signature}"


def verify_webhook_signature_header(
    payload: bytes,
    signature_header: str,
    secret: str,
    tolerance_seconds: int = TIMESTAMP_TOLERANCE_SECONDS,
) -> Tuple[bool, str | None]:
    """
    Verifica el header de firma de un webhook entrante.
    
    Args:
        payload: Cuerpo del webhook (bytes)
        signature_header: Header "X-Webhook-Signature"
        secret: Clave secreta esperada
        tolerance_seconds: Tolerancia de tiempo para prevenir replay attacks
        
    Returns:
        Tupla de (es_válido, mensaje_error)
    """
    try:
        # Parsear header
        parts = {}
        for item in signature_header.split(","):
            if "=" in item:
                key, value = item.split("=", 1)
                parts[key.strip()] = value.strip()
        
        timestamp_str = parts.get("t")
        received_signature = parts.get("v1")
        
        # DEBUG: Log del header parseado
        logger.debug(
            "Parsing webhook signature header",
            signature_header=signature_header,
            timestamp=timestamp_str,
            signature_preview=received_signature[:20] if received_signature else None,
        )
        
        if not timestamp_str or not received_signature:
            logger.warning("Invalid signature header format", parts=parts)
            return False, "Invalid signature header format"
        
        timestamp = int(timestamp_str)
        
        # Verificar que el timestamp no sea muy viejo (replay attack)
        current_time = int(time.time())
        time_diff = abs(current_time - timestamp)
        
        logger.debug(
            "Verifying webhook timestamp",
            timestamp=timestamp,
            current_time=current_time,
            difference_seconds=time_diff,
            tolerance_seconds=tolerance_seconds,
            within_tolerance=time_diff <= tolerance_seconds,
        )
        
        if time_diff > tolerance_seconds:
            logger.warning(
                "Webhook timestamp out of tolerance",
                timestamp=timestamp,
                current_time=current_time,
                difference=time_diff,
            )
            return False, "Timestamp out of tolerance"
        
        # Reconstruir el mensaje firmado
        signed_payload = f"{timestamp}.".encode("utf-8") + payload
        
        logger.debug(
            "Reconstructing signed payload",
            timestamp=timestamp,
            payload_length=len(payload),
            signed_payload_preview=(
                signed_payload[:100].decode('utf-8', errors='ignore') 
                if len(signed_payload) > 0 else ""
            ),
        )
        
        # Verificar firma
        if not verify_signature(signed_payload, received_signature, secret):
            logger.error(
                "Signature verification FAILED",
                received_signature=received_signature,
                secret_prefix=secret[:10] if secret else "None",
            )
            return False, "Invalid signature"
        
        logger.info("Signature verification SUCCESS")
        
        return True, None
        
    except ValueError as e:
        logger.error("Failed to parse signature header", error=str(e))
        return False, f"Failed to parse signature: {e}"
    except Exception as e:
        logger.error("Unexpected error verifying signature", error=str(e))
        return False, f"Verification error: {e}"


def verify_webhook_with_secrets(
    payload: bytes,
    signature_header: str,
    current_secret: str,
    previous_secret: str | None = None,
    tolerance_seconds: int = TIMESTAMP_TOLERANCE_SECONDS,
) -> Tuple[bool, str | None]:
    """
    Verifica un webhook probando múltiples secrets.
    
    Útil durante la rotación de secrets cuando el secret anterior
    aún está en periodo de gracia.
    
    Args:
        payload: Cuerpo del webhook
        signature_header: Header de firma
        current_secret: Secret actual
        previous_secret: Secret anterior (opcional)
        tolerance_seconds: Tolerancia de tiempo
        
    Returns:
        Tupla de (es_válido, mensaje_error)
    """
    # Intentar con el secret actual
    is_valid, error = verify_webhook_signature_header(
        payload, signature_header, current_secret, tolerance_seconds
    )
    
    if is_valid:
        return True, None
    
    # Si hay secret anterior, intentar con él
    if previous_secret:
        is_valid, _ = verify_webhook_signature_header(
            payload, signature_header, previous_secret, tolerance_seconds
        )
        if is_valid:
            logger.info("Webhook verified with previous secret (rotation grace period)")
            return True, None
    
    return False, error
