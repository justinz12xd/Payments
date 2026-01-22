import time
import hmac
import hashlib

secret = 'whsec_KC0oaWmHp4rdZeRhV5jRlfGt7ikLtgU8tszCjboZhdA'
body = '{"event":"service.created","source":"findyourwork","data":{"service_id":"srv-123","client_email":"cliente@example.com"}}'
timestamp = int(time.time())

message = f'{timestamp}.{body}'
signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

print(f'X-Partner-Id: 4aefbdb8-68ee-4965-aa41-278ec23081c8')
print(f'X-Webhook-Signature: t={timestamp},v1={signature}')