import time
import hmac
import hashlib
import json

# Current timestamp
timestamp = int(time.time())

# Exact payload
payload = {
    "event": "adoption.completed",
    "source": "fila-virtual",
    "data": {
        "adoption_id": "adop_123",
        "pet_name": "Max",
        "adopter_name": "Juan Pérez",
        "adoption_date": "2026-01-20"
    }
}

# JSON without spaces (compact)
payload_str = json.dumps(payload, separators=(',', ':'))

# Message to sign
message = f"{timestamp}.{payload_str}"

# Secret
secret = "whsec_834455c2816d74847f50d4f8a79646c936c356be036851dfb7242532e90976d6"

# Generate signature
signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

print(f"Current timestamp: {timestamp}")
print(f"\nX-Webhook-Signature:")
print(f"t={timestamp},v1={signature}")
print(f"\nX-Partner-Id:")
print("48aa7917-5c44-40ca-9526-57a46f85afb3")
print(f"\nRequest body:")
print(payload_str)