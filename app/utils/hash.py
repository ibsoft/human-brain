import hashlib
import json


def sha256_text(value):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def sha256_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()

