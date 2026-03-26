from __future__ import annotations

import json
from pathlib import Path


DATA_DIR = Path(__file__).parent / "data"
USERS_FILE = DATA_DIR / "users.json"


ROLE_LABELS = {
    "staff": "Staff",
    "nurse": "Nurse",
    "manager": "Manager",
    "procurement_officer": "Procurement Officer",
}


ROLE_PERMISSIONS = {
    "staff": {
        "operations_view",
        "operations_edit",
        "operations_basic",
    },
    "nurse": {
        "operations_view",
        "operations_edit",
        "operations_basic",
    },
    "manager": {
        "operations_view",
        "operations_edit",
        "operations_basic",
        "operations_advanced",
        "staff_assign",
        "procurement_view",
        "procurement_edit",
    },
    "procurement_officer": {
        "procurement_view",
        "procurement_edit",
    },
}


def _default_users() -> list[dict]:
    return [
        {
            "user_id": "NUR-1001",
            "password": "nurse123",
            "name": "Asha Nurse",
            "role": "nurse",
            "ward": "Emergency",
        },
        {
            "user_id": "STF-1001",
            "password": "staff123",
            "name": "Ravi Staff",
            "role": "staff",
            "ward": "General",
        },
        {
            "user_id": "MGR-1001",
            "password": "manager123",
            "name": "Priya Manager",
            "role": "manager",
            "ward": "Operations",
        },
        {
            "user_id": "PRO-1001",
            "password": "procure123",
            "name": "Neha Procurement",
            "role": "procurement_officer",
            "ward": "Procurement",
        },
    ]


def ensure_users_file() -> None:
    if USERS_FILE.exists():
        return
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(_default_users(), indent=2), encoding="utf-8")


def load_users() -> list[dict]:
    ensure_users_file()
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return _default_users()


def authenticate_user(user_id: str, password: str) -> dict | None:
    normalized_id = user_id.strip()
    for user in load_users():
        if user.get("user_id") == normalized_id and user.get("password") == password:
            return user
    return None


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role.replace("_", " ").title())


def has_permission(user: dict | None, permission: str) -> bool:
    if not user:
        return False
    role = str(user.get("role", "")).strip().lower()
    return permission in ROLE_PERMISSIONS.get(role, set())
