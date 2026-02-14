import secrets
import string
from datetime import datetime, timezone

import bcrypt

from database import LoginEvent, User, get_session


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def generate_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        has_upper = any(c.isupper() for c in pw)
        has_lower = any(c.islower() for c in pw)
        has_digit = any(c.isdigit() for c in pw)
        has_special = any(c in "!@#$%&*" for c in pw)
        if has_upper and has_lower and has_digit and has_special:
            return pw


def authenticate(username: str, password: str, ip_address: str | None = None) -> dict | None:
    session = get_session()
    try:
        user = session.query(User).filter_by(username=username, is_active=True).first()
        if user and verify_password(password, user.password_hash):
            user.last_login = datetime.now(timezone.utc)
            user.login_count += 1
            session.add(LoginEvent(user_id=user.id, ip_address=ip_address))
            session.commit()
            return {
                "id": user.id,
                "username": user.username,
                "name": user.name,
                "email": user.email,
                "role": user.role,
            }
        return None
    finally:
        session.close()


def init_admin() -> str | None:
    """Create initial admin if no users exist. Returns the generated password or None."""
    session = get_session()
    try:
        if session.query(User).count() > 0:
            return None
        password = generate_password()
        admin = User(
            username="admin",
            email="admin@jan-miller.de",
            password_hash=hash_password(password),
            name="Administrator",
            role="admin",
        )
        session.add(admin)
        session.commit()
        return password
    finally:
        session.close()
