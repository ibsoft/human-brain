from functools import wraps

from flask import abort
from flask_login import current_user


ROLE_ORDER = {
    "viewer": 10,
    "auditor": 20,
    "agent": 30,
    "operator": 40,
    "admin": 50,
}


def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def minimum_role(role):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(403)
            if ROLE_ORDER.get(current_user.role, 0) < ROLE_ORDER.get(role, 0):
                abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
