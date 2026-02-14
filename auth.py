import hashlib
import hmac
import json
import os
import time

USERS_FILE = os.environ.get("USERS_FILE", "users.json")


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _load_users() -> dict:
    if not os.path.exists(USERS_FILE):
        default_users = {
            "admin": {
                "password": _hash_password("123456"),
                "name": "Administrator",
                "role": "admin",
            }
        }
        with open(USERS_FILE, "w") as f:
            json.dump(default_users, f, indent=2)
        return default_users

    with open(USERS_FILE, "r") as f:
        return json.load(f)


def authenticate(username: str, password: str) -> dict | None:
    users = _load_users()
    user = users.get(username)
    if user and hmac.compare_digest(user["password"], _hash_password(password)):
        return {"username": username, "name": user["name"], "role": user["role"]}
    return None
