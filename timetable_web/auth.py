"""نظام الحسابات — مدير + مشرفون معزولون.

- ملف واحد للمستخدمين: data/users.json (بلا قاعدة بيانات، بنفس فلسفة المشروع).
- كل مشرف له ملف بيانات مدرسته الخاص في data/schools/{username}.json.
- كلمة المرور تُخزَّن كـ PBKDF2-SHA256 مع salt لكل مستخدم (stdlib فقط).
- الجلسة عبر signed cookie من starlette.SessionMiddleware.

المدير الأول يُنشأ تلقائياً بـ (admin / admin) عند أول تشغيل — يجب تغييرها فوراً.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException

from .state.store import DATA_DIR

USERS_FILE = DATA_DIR / "users.json"
SCHOOLS_DIR = DATA_DIR / "schools"

ROLE_ADMIN = "admin"
ROLE_SUPERVISOR = "supervisor"


@dataclass
class User:
    username: str
    password_hash: str
    salt: str
    role: str
    active: bool = True
    data_file: str | None = None  # relative name inside schools/, None for admin
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()


def make_user(username: str, password: str, role: str,
              data_file: str | None = None, active: bool = True) -> User:
    salt = secrets.token_hex(16)
    return User(
        username=username,
        password_hash=_hash_password(password, salt),
        salt=salt,
        role=role,
        active=active,
        data_file=data_file,
    )


def load_users() -> list[User]:
    if not USERS_FILE.exists():
        return []
    raw = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    return [User(**u) for u in raw.get("users", [])]


def save_users(users: list[User]) -> None:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(
        json.dumps({"users": [asdict(u) for u in users]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def find_user(username: str | None) -> User | None:
    if not username:
        return None
    for u in load_users():
        if u.username == username:
            return u
    return None


def verify_password(user: User, password: str) -> bool:
    return _hash_password(password, user.salt) == user.password_hash


def update_user(username: str, **fields) -> User:
    users = load_users()
    for u in users:
        if u.username == username:
            for k, v in fields.items():
                setattr(u, k, v)
            save_users(users)
            return u
    raise ValueError(f"لا يوجد مستخدم باسم {username}")


def delete_user(username: str) -> None:
    users = load_users()
    keep = [u for u in users if u.username != username]
    if len(keep) == len(users):
        raise ValueError(f"لا يوجد مستخدم باسم {username}")
    save_users(keep)


def bootstrap_admin() -> User | None:
    """إنشاء المدير الأول تلقائياً عند غياب أي مستخدم."""
    SCHOOLS_DIR.mkdir(parents=True, exist_ok=True)
    if load_users():
        return None
    admin = make_user("admin", "admin", ROLE_ADMIN)
    save_users([admin])
    print("=" * 60)
    print("⚠️  تم إنشاء حساب المدير الافتراضي:")
    print("       المستخدم:      admin")
    print("       كلمة المرور:   admin")
    print("   ⚠️  غيّرها فوراً من صفحة /admin بعد أول تسجيل دخول!")
    print("=" * 60)
    return admin


# ---------------------------------------------------------------------------
# ContextVar المستخدم الحالي — يضبطه AuthMiddleware في كل طلب
# ---------------------------------------------------------------------------

_current_user: ContextVar[User | None] = ContextVar("current_user", default=None)


def set_current_user(user: User | None) -> None:
    _current_user.set(user)


def current_user() -> User | None:
    return _current_user.get()


def require_user() -> User:
    u = current_user()
    if u is None:
        raise HTTPException(401, "يجب تسجيل الدخول")
    return u


def require_admin() -> User:
    u = require_user()
    if not u.is_admin():
        raise HTTPException(403, "هذه الصفحة للمدير فقط")
    return u
