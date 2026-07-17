"""Local, transactional credential pools for supported AI providers.

The SQLite store lives outside the repository by default. Secret values and
safe operational metadata use separate tables inside one mode-0600 database so
updates can remain transactional. OS keyring-backed encryption is a future
hardening step; filesystem permissions are the Phase 1 protection boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import random
import secrets
import sqlite3
import stat
import threading
import time
import unicodedata
import uuid

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.core.config import PROVIDER_CREDENTIAL_FIELDS, settings
from app.core.providers.base import ProviderCredential


MAX_LABEL_LENGTH = 80
MAX_SECRET_LENGTH = 8192
MAX_PRIORITY = 1000
MAX_DAILY_REQUEST_CAP = 1_000_000
MAX_RATE_LIMIT_COOLDOWN_SECONDS = 3600.0
MAX_TRANSIENT_COOLDOWN_SECONDS = 60.0
_UNSET = object()
SQLITE_STORE_SUFFIXES = ("", "-journal", "-wal", "-shm")


class CredentialPoolError(RuntimeError):
    """Base error carrying only a safe machine-readable code."""

    code = "credential_pool_error"


class CredentialPoolValidationError(CredentialPoolError):
    code = "invalid_credential_request"


class CredentialNotFoundError(CredentialPoolError):
    code = "credential_not_found"


@dataclass(frozen=True)
class CredentialLease:
    """Internal-only credential lease whose representation never shows a key."""

    credential_id: str
    provider_id: str
    credential: ProviderCredential = field(repr=False)

    def __repr__(self) -> str:
        return (
            "CredentialLease(credential_id="
            f"{self.credential_id!r}, provider_id={self.provider_id!r}, "
            "credential=**********)"
        )


class CredentialPoolManager:
    """Manage provider credentials, health, cooldowns, and fair selection."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        clock: Callable[[], float] = time.time,
        random_source: Callable[[], float] | None = None,
    ):
        self.database_path = Path(database_path).expanduser()
        self._clock = clock
        self._random = random_source or random.SystemRandom().random
        self._process_lock = threading.RLock()
        self._provider_locks: dict[str, asyncio.Lock] = {}
        self._round_robin_cursor: dict[tuple[str, int], int] = {}
        self._initialized = False

    def _secure_store_files(self) -> None:
        """Keep the database and any SQLite sidecars owner-readable only."""
        for suffix in SQLITE_STORE_SUFFIXES:
            path = Path(f"{self.database_path}{suffix}")
            try:
                file_status = path.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(file_status.st_mode):
                raise CredentialPoolError("Credential store is unavailable")
            try:
                os.chmod(path, 0o600)
            except OSError:
                raise CredentialPoolError(
                    "Credential store is unavailable"
                ) from None

    def _close_connection(self, connection: sqlite3.Connection) -> None:
        try:
            connection.close()
        finally:
            self._secure_store_files()

    def _ensure_database(self) -> None:
        with self._process_lock:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(self.database_path.parent, 0o700)
            self._secure_store_files()
            if self._initialized and self.database_path.exists():
                return
            if not self.database_path.exists():
                descriptor = os.open(
                    self.database_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                os.close(descriptor)
            os.chmod(self.database_path, 0o600)
            connection = sqlite3.connect(self.database_path)
            try:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("PRAGMA journal_mode = DELETE")
                connection.execute("PRAGMA synchronous = FULL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS pool_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS credential_metadata (
                        credential_id TEXT PRIMARY KEY,
                        provider TEXT NOT NULL,
                        label TEXT NOT NULL,
                        enabled INTEGER NOT NULL,
                        priority INTEGER NOT NULL,
                        created_at REAL NOT NULL,
                        last_used_at REAL,
                        last_success_at REAL,
                        last_failure_at REAL,
                        fingerprint TEXT NOT NULL,
                        failure_count INTEGER NOT NULL DEFAULT 0,
                        cooldown_until REAL,
                        invalid INTEGER NOT NULL DEFAULT 0,
                        daily_request_cap INTEGER,
                        daily_request_count INTEGER NOT NULL DEFAULT 0,
                        daily_request_date TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS credential_secrets (
                        credential_id TEXT PRIMARY KEY,
                        secret_value TEXT NOT NULL,
                        FOREIGN KEY (credential_id)
                            REFERENCES credential_metadata(credential_id)
                            ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_credential_provider
                    ON credential_metadata(provider, priority, created_at);
                    """
                )
                if connection.execute(
                    "SELECT 1 FROM pool_settings WHERE key = ?",
                    ("fingerprint_salt",),
                ).fetchone() is None:
                    connection.execute(
                        "INSERT INTO pool_settings(key, value) VALUES (?, ?)",
                        ("fingerprint_salt", secrets.token_hex(32)),
                    )
                connection.commit()
            finally:
                self._close_connection(connection)
            self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        self._ensure_database()
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        self._secure_store_files()
        return connection

    @staticmethod
    def _validate_provider(provider: str) -> str:
        if not isinstance(provider, str):
            raise CredentialPoolValidationError("Credential request is invalid")
        normalized = provider.strip().lower()
        if normalized not in PROVIDER_CREDENTIAL_FIELDS:
            raise CredentialPoolValidationError("Credential request is invalid")
        return normalized

    @staticmethod
    def _validate_label(label: str) -> str:
        if not isinstance(label, str):
            raise CredentialPoolValidationError("Credential request is invalid")
        normalized = label.strip()
        if (
            not normalized
            or len(normalized) > MAX_LABEL_LENGTH
            or any(unicodedata.category(character) == "Cc" for character in normalized)
        ):
            raise CredentialPoolValidationError("Credential request is invalid")
        return normalized

    @staticmethod
    def _validate_secret(secret_value: str) -> str:
        if not isinstance(secret_value, str):
            raise CredentialPoolValidationError("Credential request is invalid")
        if (
            len(secret_value) < 8
            or len(secret_value) > MAX_SECRET_LENGTH
            or secret_value != secret_value.strip()
            or any(unicodedata.category(character) == "Cc" for character in secret_value)
        ):
            raise CredentialPoolValidationError("Credential request is invalid")
        return secret_value

    @staticmethod
    def _validate_priority(priority: int) -> int:
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise CredentialPoolValidationError("Credential request is invalid")
        if not 0 <= priority <= MAX_PRIORITY:
            raise CredentialPoolValidationError("Credential request is invalid")
        return priority

    @staticmethod
    def _validate_daily_cap(daily_request_cap: int | None) -> int | None:
        if daily_request_cap is None:
            return None
        if isinstance(daily_request_cap, bool) or not isinstance(daily_request_cap, int):
            raise CredentialPoolValidationError("Credential request is invalid")
        if not 1 <= daily_request_cap <= MAX_DAILY_REQUEST_CAP:
            raise CredentialPoolValidationError("Credential request is invalid")
        return daily_request_cap

    @staticmethod
    def _today(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()

    @staticmethod
    def _timestamp(timestamp: float | None) -> str | None:
        if timestamp is None:
            return None
        return (
            datetime.fromtimestamp(timestamp, timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )

    @staticmethod
    def _row_exists(connection: sqlite3.Connection, credential_id: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM credential_metadata WHERE credential_id = ?",
            (credential_id,),
        ).fetchone() is not None

    @staticmethod
    def _safe_credential_id(credential_id: str) -> str:
        if not isinstance(credential_id, str):
            raise CredentialNotFoundError("Credential was not found")
        try:
            return str(uuid.UUID(credential_id))
        except (ValueError, AttributeError):
            raise CredentialNotFoundError("Credential was not found") from None

    def _fingerprint(self, connection: sqlite3.Connection, secret_value: str) -> str:
        row = connection.execute(
            "SELECT value FROM pool_settings WHERE key = ?",
            ("fingerprint_salt",),
        ).fetchone()
        if row is None:
            raise CredentialPoolError("Credential store is unavailable")
        salt = bytes.fromhex(str(row["value"]))
        digest = hmac.new(
            salt,
            secret_value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"fp_{digest[:16]}"

    def _reset_daily_usage(
        self,
        connection: sqlite3.Connection,
        provider: str | None,
        now: float,
    ) -> None:
        today = self._today(now)
        if provider is None:
            connection.execute(
                """
                UPDATE credential_metadata
                SET daily_request_count = 0, daily_request_date = ?
                WHERE daily_request_date != ?
                """,
                (today, today),
            )
        else:
            connection.execute(
                """
                UPDATE credential_metadata
                SET daily_request_count = 0, daily_request_date = ?
                WHERE provider = ? AND daily_request_date != ?
                """,
                (today, provider, today),
            )

    def _health_status(self, row: sqlite3.Row, now: float) -> str:
        if bool(row["invalid"]):
            return "invalid"
        if not bool(row["enabled"]):
            return "disabled"
        cap = row["daily_request_cap"]
        if cap is not None and int(row["daily_request_count"]) >= int(cap):
            return "daily_cap_reached"
        cooldown_until = row["cooldown_until"]
        if cooldown_until is not None and float(cooldown_until) > now:
            return "cooldown"
        return "healthy"

    def _safe_metadata(self, row: sqlite3.Row, now: float) -> dict[str, object]:
        return {
            "credential_id": str(row["credential_id"]),
            "provider": str(row["provider"]),
            "label": str(row["label"]),
            "enabled": bool(row["enabled"]),
            "priority": int(row["priority"]),
            "created_at": self._timestamp(float(row["created_at"])),
            "last_used_at": self._timestamp(row["last_used_at"]),
            "last_success_at": self._timestamp(row["last_success_at"]),
            "last_failure_at": self._timestamp(row["last_failure_at"]),
            "fingerprint": str(row["fingerprint"]),
            "failure_count": int(row["failure_count"]),
            "cooldown_until": self._timestamp(row["cooldown_until"]),
            "invalid": bool(row["invalid"]),
            "daily_request_cap": row["daily_request_cap"],
            "daily_request_count": int(row["daily_request_count"]),
            "daily_request_date": str(row["daily_request_date"]),
            "health_status": self._health_status(row, now),
        }

    def add_credential(
        self,
        provider: str,
        label: str,
        secret_value: str,
        *,
        enabled: bool = True,
        priority: int = 100,
        daily_request_cap: int | None = None,
    ) -> dict[str, object]:
        normalized_provider = self._validate_provider(provider)
        normalized_label = self._validate_label(label)
        normalized_secret = self._validate_secret(secret_value)
        normalized_priority = self._validate_priority(priority)
        normalized_cap = self._validate_daily_cap(daily_request_cap)
        if not isinstance(enabled, bool):
            raise CredentialPoolValidationError("Credential request is invalid")

        credential_id = str(uuid.uuid4())
        now = self._clock()
        today = self._today(now)
        with self._process_lock:
            connection = self._connect()
            try:
                with connection:
                    fingerprint = self._fingerprint(connection, normalized_secret)
                    connection.execute(
                        """
                        INSERT INTO credential_metadata(
                            credential_id, provider, label, enabled, priority,
                            created_at, fingerprint, daily_request_cap,
                            daily_request_date
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            credential_id,
                            normalized_provider,
                            normalized_label,
                            int(enabled),
                            normalized_priority,
                            now,
                            fingerprint,
                            normalized_cap,
                            today,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO credential_secrets(credential_id, secret_value)
                        VALUES (?, ?)
                        """,
                        (credential_id, normalized_secret),
                    )
                    row = connection.execute(
                        "SELECT * FROM credential_metadata WHERE credential_id = ?",
                        (credential_id,),
                    ).fetchone()
            finally:
                self._close_connection(connection)
        if row is None:
            raise CredentialPoolError("Credential store is unavailable")
        return self._safe_metadata(row, now)

    def update_credential(
        self,
        credential_id: str,
        *,
        label: str | object = _UNSET,
        enabled: bool | object = _UNSET,
        priority: int | object = _UNSET,
        daily_request_cap: int | None | object = _UNSET,
        secret_value: str | object = _UNSET,
    ) -> dict[str, object]:
        safe_id = self._safe_credential_id(credential_id)
        updates: dict[str, object] = {}
        if label is not _UNSET:
            updates["label"] = self._validate_label(label)  # type: ignore[arg-type]
        if enabled is not _UNSET:
            if not isinstance(enabled, bool):
                raise CredentialPoolValidationError("Credential request is invalid")
            updates["enabled"] = int(enabled)
        if priority is not _UNSET:
            updates["priority"] = self._validate_priority(priority)  # type: ignore[arg-type]
        if daily_request_cap is not _UNSET:
            updates["daily_request_cap"] = self._validate_daily_cap(
                daily_request_cap  # type: ignore[arg-type]
            )
        normalized_secret: str | object = _UNSET
        if secret_value is not _UNSET:
            normalized_secret = self._validate_secret(secret_value)  # type: ignore[arg-type]

        with self._process_lock:
            connection = self._connect()
            try:
                with connection:
                    current = connection.execute(
                        "SELECT * FROM credential_metadata WHERE credential_id = ?",
                        (safe_id,),
                    ).fetchone()
                    if current is None:
                        raise CredentialNotFoundError("Credential was not found")
                    if updates.get("enabled") == 1 and bool(current["invalid"]):
                        if normalized_secret is _UNSET:
                            raise CredentialPoolValidationError(
                                "Credential must be replaced before enabling"
                            )
                    if normalized_secret is not _UNSET:
                        connection.execute(
                            """
                            UPDATE credential_secrets
                            SET secret_value = ? WHERE credential_id = ?
                            """,
                            (normalized_secret, safe_id),
                        )
                        updates.update(
                            {
                                "fingerprint": self._fingerprint(
                                    connection,
                                    normalized_secret,
                                ),
                                "invalid": 0,
                                "failure_count": 0,
                                "cooldown_until": None,
                                "last_failure_at": None,
                            }
                        )
                    if updates:
                        assignments = ", ".join(f"{field} = ?" for field in updates)
                        connection.execute(
                            f"UPDATE credential_metadata SET {assignments} "
                            "WHERE credential_id = ?",
                            (*updates.values(), safe_id),
                        )
                    row = connection.execute(
                        "SELECT * FROM credential_metadata WHERE credential_id = ?",
                        (safe_id,),
                    ).fetchone()
            finally:
                self._close_connection(connection)
        if row is None:
            raise CredentialNotFoundError("Credential was not found")
        return self._safe_metadata(row, self._clock())

    def replace_credential(
        self,
        credential_id: str,
        secret_value: str,
    ) -> dict[str, object]:
        return self.update_credential(
            credential_id,
            secret_value=secret_value,
        )

    def remove_credential(self, credential_id: str) -> None:
        safe_id = self._safe_credential_id(credential_id)
        with self._process_lock:
            connection = self._connect()
            try:
                with connection:
                    if not self._row_exists(connection, safe_id):
                        raise CredentialNotFoundError("Credential was not found")
                    connection.execute(
                        "DELETE FROM credential_metadata WHERE credential_id = ?",
                        (safe_id,),
                    )
            finally:
                self._close_connection(connection)

    def enable_credential(self, credential_id: str) -> dict[str, object]:
        return self.update_credential(credential_id, enabled=True)

    def disable_credential(self, credential_id: str) -> dict[str, object]:
        return self.update_credential(credential_id, enabled=False)

    def has_credentials(self, provider: str) -> bool:
        normalized_provider = self._validate_provider(provider)
        if not self.database_path.exists():
            return False
        with self._process_lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT 1 FROM credential_metadata WHERE provider = ? LIMIT 1",
                    (normalized_provider,),
                ).fetchone()
            finally:
                self._close_connection(connection)
        return row is not None

    def list_safe_metadata(
        self,
        provider: str | None = None,
    ) -> list[dict[str, object]]:
        normalized_provider = (
            self._validate_provider(provider) if provider is not None else None
        )
        if not self.database_path.exists():
            return []
        now = self._clock()
        with self._process_lock:
            connection = self._connect()
            try:
                with connection:
                    self._reset_daily_usage(connection, normalized_provider, now)
                    if normalized_provider is None:
                        rows = connection.execute(
                            """
                            SELECT * FROM credential_metadata
                            ORDER BY provider, priority, created_at, credential_id
                            """
                        ).fetchall()
                    else:
                        rows = connection.execute(
                            """
                            SELECT * FROM credential_metadata
                            WHERE provider = ?
                            ORDER BY priority, created_at, credential_id
                            """,
                            (normalized_provider,),
                        ).fetchall()
            finally:
                self._close_connection(connection)
        return [self._safe_metadata(row, now) for row in rows]

    def _provider_lock(self, provider: str) -> asyncio.Lock:
        with self._process_lock:
            lock = self._provider_locks.get(provider)
            if lock is None:
                lock = asyncio.Lock()
                self._provider_locks[provider] = lock
            return lock

    async def acquire(self, provider: str) -> CredentialLease | None:
        normalized_provider = self._validate_provider(provider)
        async with self._provider_lock(normalized_provider):
            if not self.database_path.exists():
                return None
            now = self._clock()
            with self._process_lock:
                connection = self._connect()
                try:
                    with connection:
                        self._reset_daily_usage(connection, normalized_provider, now)
                        rows = connection.execute(
                            """
                            SELECT metadata.*, secrets.secret_value
                            FROM credential_metadata AS metadata
                            JOIN credential_secrets AS secrets USING (credential_id)
                            WHERE metadata.provider = ?
                              AND metadata.enabled = 1
                              AND metadata.invalid = 0
                              AND (
                                  metadata.cooldown_until IS NULL
                                  OR metadata.cooldown_until <= ?
                              )
                              AND (
                                  metadata.daily_request_cap IS NULL
                                  OR metadata.daily_request_count
                                      < metadata.daily_request_cap
                              )
                            ORDER BY metadata.priority,
                                     metadata.created_at,
                                     metadata.credential_id
                            """,
                            (normalized_provider, now),
                        ).fetchall()
                        if not rows:
                            return None

                        best_priority = int(rows[0]["priority"])
                        candidates = [
                            row for row in rows if int(row["priority"]) == best_priority
                        ]
                        cursor_key = (normalized_provider, best_priority)
                        cursor = self._round_robin_cursor.get(cursor_key, 0)
                        selected = candidates[cursor % len(candidates)]
                        self._round_robin_cursor[cursor_key] = (
                            cursor + 1
                        ) % len(candidates)
                        connection.execute(
                            """
                            UPDATE credential_metadata
                            SET last_used_at = ?,
                                daily_request_count = daily_request_count + 1
                            WHERE credential_id = ?
                            """,
                            (now, selected["credential_id"]),
                        )
                        credential_id = str(selected["credential_id"])
                        secret_value = str(selected["secret_value"])
                finally:
                    self._close_connection(connection)

            return CredentialLease(
                credential_id=credential_id,
                provider_id=normalized_provider,
                credential=ProviderCredential(
                    provider_id=normalized_provider,
                    secret=secret_value,
                ),
            )

    def record_success(self, credential_id: str) -> None:
        safe_id = self._safe_credential_id(credential_id)
        now = self._clock()
        with self._process_lock:
            connection = self._connect()
            try:
                with connection:
                    cursor = connection.execute(
                        """
                        UPDATE credential_metadata
                        SET last_success_at = ?, failure_count = 0,
                            cooldown_until = NULL
                        WHERE credential_id = ?
                        """,
                        (now, safe_id),
                    )
                    if cursor.rowcount != 1:
                        raise CredentialNotFoundError("Credential was not found")
            finally:
                self._close_connection(connection)

    def _cooldown_seconds(
        self,
        reason: str,
        failure_count: int,
        retry_after_seconds: float | None,
    ) -> float:
        if reason == "rate_limit" and retry_after_seconds is not None:
            return min(
                MAX_RATE_LIMIT_COOLDOWN_SECONDS,
                max(1.0, float(retry_after_seconds)),
            )
        if reason == "rate_limit":
            base = min(900.0, 30.0 * (2 ** max(0, failure_count - 1)))
            maximum = MAX_RATE_LIMIT_COOLDOWN_SECONDS
        else:
            base = min(45.0, 5.0 * (2 ** max(0, failure_count - 1)))
            maximum = MAX_TRANSIENT_COOLDOWN_SECONDS
        jittered = base * (0.8 + (0.4 * self._random()))
        return min(maximum, max(1.0, jittered))

    def record_failure(
        self,
        credential_id: str,
        reason: str,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        safe_id = self._safe_credential_id(credential_id)
        if reason not in {
            "authentication",
            "rate_limit",
            "timeout",
            "connection",
            "upstream",
        }:
            raise CredentialPoolValidationError("Credential request is invalid")
        now = self._clock()
        with self._process_lock:
            connection = self._connect()
            try:
                with connection:
                    row = connection.execute(
                        """
                        SELECT failure_count FROM credential_metadata
                        WHERE credential_id = ?
                        """,
                        (safe_id,),
                    ).fetchone()
                    if row is None:
                        raise CredentialNotFoundError("Credential was not found")
                    failure_count = int(row["failure_count"]) + 1
                    if reason == "authentication":
                        connection.execute(
                            """
                            UPDATE credential_metadata
                            SET failure_count = ?, last_failure_at = ?,
                                invalid = 1, enabled = 0,
                                cooldown_until = NULL
                            WHERE credential_id = ?
                            """,
                            (failure_count, now, safe_id),
                        )
                    else:
                        cooldown = self._cooldown_seconds(
                            reason,
                            failure_count,
                            retry_after_seconds,
                        )
                        connection.execute(
                            """
                            UPDATE credential_metadata
                            SET failure_count = ?, last_failure_at = ?,
                                cooldown_until = ?
                            WHERE credential_id = ?
                            """,
                            (failure_count, now, now + cooldown, safe_id),
                        )
            finally:
                self._close_connection(connection)


credential_pool_manager = CredentialPoolManager(settings.CREDENTIAL_STORE_PATH)
