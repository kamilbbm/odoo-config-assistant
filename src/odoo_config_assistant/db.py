"""Application database (SFD 1.1 "Base de données applicative", 4.6 data model).

SQLite (standard library, a single file, no server). Tables: organisation, users, projects,
project members, assistant exchanges, deliverables, notifications. A project keeps its profile
and plan as a JSON document (models.Project), as in the V0 files.

Location: ``OCA_DB`` environment variable, by default ``var/assistant.db`` (ignored by git).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from odoo_config_assistant.models import Project

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT / "var" / "assistant.db"
_PBKDF2_ROUNDS = 240_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS organisation (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_members (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (project_id, user_id)
);
CREATE TABLE IF NOT EXISTS exchanges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    step_id TEXT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deliverables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    format TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS repository_files (
    name TEXT PRIMARY KEY,
    content TEXT,
    updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS repository_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS step_reviews (
    step_id TEXT NOT NULL,
    report_id TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (step_id, report_id)
);
CREATE TABLE IF NOT EXISTS gap_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    project_id TEXT,
    step_id TEXT,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Role(StrEnum):
    ADMIN = "admin"
    REFERENT = "referent"
    CONSULTANT = "consultant"
    CLIENT = "client"

    @property
    def label(self) -> str:
        return ROLE_LABELS[self]


ROLE_LABELS = {
    Role.ADMIN: "Administrateur",
    Role.REFERENT: "Référent contenu",
    Role.CONSULTANT: "Consultant",
    Role.CLIENT: "Utilisateur client",
}


class Organisation(BaseModel):
    """Identity and parameters of the user organisation (F-001, RG-013): nothing hard-coded."""

    name: str
    mentions: str = ""
    logo_b64: str | None = None
    logo_mime: str | None = None
    # Paramètres (SFD 4.6) : seuils de synchronisation (Q-003, Q-004).
    drop_threshold: float = 0.05
    translation_threshold: float = 0.8
    # Messagerie (2.1.5) : serveur SMTP ; le mot de passe vient de la variable OCA_SMTP_PASSWORD.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_sender: str | None = None
    smtp_starttls: bool = True
    demo: bool = False

    @field_validator("name")
    @classmethod
    def _name_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("le nom de l'organisation est obligatoire")
        return value.strip()


class User(BaseModel):
    id: int
    email: str
    name: str
    role: Role
    active: bool = True

    @property
    def label(self) -> str:
        return f"{self.name} ({self.role.label})"


class Exchange(BaseModel):
    """Exchange with the assistant (4.6), kept with the documentation version (RG-008)."""

    id: int | None = None
    project_id: str | None = None
    step_id: str | None = None
    user_id: int | None = None
    question: str
    text: str
    covered: bool
    mode: str
    citations: list[dict] = Field(default_factory=list)
    doc_commit: str | None = None
    version: str
    created_at: str = Field(default_factory=_now)


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("le mot de passe doit faire au moins 8 caractères")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt, digest = stored.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
    return hmac.compare_digest(candidate.hex(), digest)


class Database:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or os.environ.get("OCA_DB") or DEFAULT_DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ----------------------------------------------------------------------- organisation

    def organisation(self) -> Organisation | None:
        with self.connect() as con:
            row = con.execute("SELECT data FROM organisation WHERE id = 1").fetchone()
        return Organisation.model_validate_json(row["data"]) if row else None

    def save_organisation(self, organisation: Organisation) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO organisation (id, data) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                (organisation.model_dump_json(),),
            )

    # ----------------------------------------------------------------------- users

    @staticmethod
    def _user(row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            email=row["email"],
            name=row["name"],
            role=Role(row["role"]),
            active=bool(row["active"]),
        )

    def create_user(self, email: str, name: str, role: Role, password: str) -> User:
        email = email.strip().lower()
        if "@" not in email:
            raise ValueError("adresse de courriel invalide")
        if not name.strip():
            raise ValueError("le nom est obligatoire")
        try:
            with self.connect() as con:
                cur = con.execute(
                    "INSERT INTO users (email, name, role, password_hash, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (email, name.strip(), Role(role).value, hash_password(password), _now()),
                )
                user_id = cur.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"un utilisateur existe déjà avec l'adresse {email}") from exc
        return self.user(user_id)

    def user(self, user_id: int) -> User:
        with self.connect() as con:
            row = con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise KeyError(user_id)
        return self._user(row)

    def user_by_email(self, email: str) -> User | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
            ).fetchone()
        return self._user(row) if row else None

    def users(self) -> list[User]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM users ORDER BY role, name").fetchall()
        return [self._user(r) for r in rows]

    def authenticate(self, email: str, password: str) -> User | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
            ).fetchone()
        if row is None or not row["active"] or not verify_password(password, row["password_hash"]):
            return None
        return self._user(row)

    def update_user(
        self,
        user_id: int,
        *,
        name: str | None = None,
        role: Role | None = None,
        active: bool | None = None,
        password: str | None = None,
    ) -> User:
        user = self.user(user_id)
        if user.role is Role.ADMIN and (
            (role is not None and role is not Role.ADMIN) or active is False
        ):
            admins = [u for u in self.users() if u.role is Role.ADMIN and u.active]
            if len(admins) <= 1:
                raise ValueError("l'organisation doit garder au moins un administrateur actif")
        with self.connect() as con:
            if name is not None:
                con.execute("UPDATE users SET name = ? WHERE id = ?", (name.strip(), user_id))
            if role is not None:
                con.execute("UPDATE users SET role = ? WHERE id = ?", (Role(role).value, user_id))
            if active is not None:
                con.execute("UPDATE users SET active = ? WHERE id = ?", (int(active), user_id))
            if password is not None:
                con.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (hash_password(password), user_id),
                )
        return self.user(user_id)

    # ----------------------------------------------------------------------- projects

    def save_project(self, project: Project) -> Project:
        project = project.model_copy(update={"updated_at": datetime.now(UTC)})
        with self.connect() as con:
            con.execute(
                "INSERT INTO projects (id, data, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data, "
                "updated_at = excluded.updated_at",
                (project.id, project.model_dump_json(), project.updated_at.isoformat()),
            )
        return project

    def import_project(self, project: Project) -> Project:
        """Store a project as is (seed), keeping its own timestamps."""
        with self.connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO projects (id, data, updated_at) VALUES (?, ?, ?)",
                (project.id, project.model_dump_json(), project.updated_at.isoformat()),
            )
        return project

    def project(self, project_id: str) -> Project:
        with self.connect() as con:
            row = con.execute("SELECT data FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(project_id)
        return Project.model_validate_json(row["data"])

    def projects(self) -> list[Project]:
        """All projects, most recently updated first."""
        with self.connect() as con:
            rows = con.execute("SELECT data FROM projects ORDER BY updated_at DESC").fetchall()
        return [Project.model_validate_json(r["data"]) for r in rows]

    def delete_project(self, project_id: str) -> None:
        with self.connect() as con:
            con.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def add_member(self, project_id: str, user_id: int) -> None:
        user = self.user(user_id)
        if user.role not in (Role.CONSULTANT, Role.CLIENT):
            raise ValueError("seuls les consultants et les utilisateurs clients sont membres")
        with self.connect() as con:
            con.execute(
                "INSERT OR IGNORE INTO project_members (project_id, user_id) VALUES (?, ?)",
                (project_id, user_id),
            )

    def remove_member(self, project_id: str, user_id: int) -> None:
        with self.connect() as con:
            con.execute(
                "DELETE FROM project_members WHERE project_id = ? AND user_id = ?",
                (project_id, user_id),
            )

    def members(self, project_id: str) -> list[User]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT u.* FROM users u JOIN project_members m ON m.user_id = u.id "
                "WHERE m.project_id = ? ORDER BY u.role, u.name",
                (project_id,),
            ).fetchall()
        return [self._user(r) for r in rows]

    def member_project_ids(self, user_id: int) -> set[str]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT project_id FROM project_members WHERE user_id = ?", (user_id,)
            ).fetchall()
        return {r["project_id"] for r in rows}

    # ----------------------------------------------------------------------- exchanges

    def add_exchange(self, exchange: Exchange) -> Exchange:
        with self.connect() as con:
            cur = con.execute(
                "INSERT INTO exchanges (project_id, step_id, user_id, data, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    exchange.project_id,
                    exchange.step_id,
                    exchange.user_id,
                    exchange.model_dump_json(exclude={"id"}),
                    exchange.created_at,
                ),
            )
            exchange_id = cur.lastrowid
        return exchange.model_copy(update={"id": exchange_id})

    def exchanges(
        self, project_id: str | None, step_id: str | None = None, user_id: int | None = None
    ) -> list[Exchange]:
        """Exchanges of a project (or outside any project), most recent first."""
        query = "SELECT id, data FROM exchanges WHERE "
        params: list = []
        if project_id is None:
            query += "project_id IS NULL"
        else:
            query += "project_id = ?"
            params.append(project_id)
        if step_id is not None:
            query += " AND step_id = ?"
            params.append(step_id)
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        query += " ORDER BY id DESC"
        with self.connect() as con:
            rows = con.execute(query, params).fetchall()
        return [Exchange.model_validate({**json.loads(r["data"]), "id": r["id"]}) for r in rows]

    # ----------------------------------------------------------------------- deliverables

    def log_deliverable(self, project_id: str, kind: str, fmt: str, user_id: int | None) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO deliverables (project_id, kind, format, user_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (project_id, kind, fmt, user_id, _now()),
            )

    def deliverables(self, project_id: str) -> list[dict]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT d.kind, d.format, d.created_at, u.name AS user_name "
                "FROM deliverables d LEFT JOIN users u ON u.id = d.user_id "
                "WHERE d.project_id = ? ORDER BY d.id DESC",
                (project_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ----------------------------------------------------------------------- notifications

    def log_notification(
        self,
        kind: str,
        recipient: str,
        subject: str,
        body: str,
        status: str,
        error: str | None = None,
        project_id: str | None = None,
        step_id: str | None = None,
    ) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO notifications (kind, recipient, subject, body, status, error, "
                "project_id, step_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kind, recipient, subject, body, status, error, project_id, step_id, _now()),
            )

    def notifications(self, limit: int = 100) -> list[dict]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ----------------------------------------------------------------------- repository (E-09)

    def repository_overrides(self) -> dict[str, str | None]:
        with self.connect() as con:
            rows = con.execute("SELECT name, content FROM repository_files").fetchall()
        return {r["name"]: r["content"] for r in rows}

    def repository_version(self) -> str:
        """Changes whenever the edited repository changes (cache key of the catalog)."""
        with self.connect() as con:
            row = con.execute(
                "SELECT COUNT(*) AS n, MAX(updated_at) AS at FROM repository_files"
            ).fetchone()
            last = con.execute("SELECT MAX(id) AS id FROM repository_history").fetchone()
        return f"{row['n']}-{row['at']}-{last['id']}"

    def save_repository_file(
        self, name: str, content: str | None, user_id: int | None, action: str, detail: str
    ) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO repository_files (name, content, updated_by, updated_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET content = excluded.content, "
                "updated_by = excluded.updated_by, updated_at = excluded.updated_at",
                (name, content, user_id, _now()),
            )
            con.execute(
                "INSERT INTO repository_history (name, action, detail, user_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, action, detail, user_id, _now()),
            )

    def reset_repository_file(self, name: str, user_id: int | None) -> None:
        with self.connect() as con:
            con.execute("DELETE FROM repository_files WHERE name = ?", (name,))
            con.execute(
                "INSERT INTO repository_history (name, action, detail, user_id, created_at) "
                "VALUES (?, 'rétablissement', 'version livrée rétablie', ?, ?)",
                (name, user_id, _now()),
            )

    def repository_history(self, limit: int = 50) -> list[dict]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT h.name, h.action, h.detail, h.created_at, u.name AS user_name "
                "FROM repository_history h LEFT JOIN users u ON u.id = h.user_id "
                "ORDER BY h.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def review_step(self, step_id: str, report_id: str, user_id: int | None) -> None:
        """The content owner has revalidated a step after a documentation change (RG-011)."""
        with self.connect() as con:
            con.execute(
                "INSERT OR IGNORE INTO step_reviews (step_id, report_id, user_id, created_at) "
                "VALUES (?, ?, ?, ?)",
                (step_id, report_id, user_id, _now()),
            )

    def reviewed_steps(self, report_id: str) -> set[str]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT step_id FROM step_reviews WHERE report_id = ?", (report_id,)
            ).fetchall()
        return {r["step_id"] for r in rows}

    # ----------------------------------------------------------------------- gap control (F-014)

    def save_gap_report(self, project_id: str, user_id: int | None, data: str) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO gap_checks (project_id, user_id, data, created_at) "
                "VALUES (?, ?, ?, ?)",
                (project_id, user_id, data, _now()),
            )

    def gap_reports(self, project_id: str) -> list[str]:
        """Stored reports (JSON), most recent first."""
        with self.connect() as con:
            rows = con.execute(
                "SELECT data FROM gap_checks WHERE project_id = ? ORDER BY id DESC", (project_id,)
            ).fetchall()
        return [r["data"] for r in rows]
