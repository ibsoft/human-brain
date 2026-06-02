import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote


def generate_totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def provisioning_uri(secret, email, issuer="Human-Brain"):
    label = f"{issuer}:{email}"
    return f"otpauth://totp/{quote(label)}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"


def totp_code(secret, for_time=None, step=30):
    timestamp = int(time.time() if for_time is None else for_time)
    counter = timestamp // step
    padded = secret.upper() + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    token = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{token % 1000000:06d}"


def verify_totp(secret, code, window=1, for_time=None):
    clean = "".join(char for char in str(code or "") if char.isdigit())
    if len(clean) != 6:
        return False
    now = int(time.time() if for_time is None else for_time)
    for offset in range(-window, window + 1):
        if hmac.compare_digest(totp_code(secret, now + offset * 30), clean):
            return True
    return False
