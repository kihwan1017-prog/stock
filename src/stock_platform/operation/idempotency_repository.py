from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Callable, TypeVar

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stock_platform.operation.idempotency_entities import (
    IdempotencyRecord,
)

T = TypeVar("T")


class IdempotencyConflictError(RuntimeError):
    pass


class IdempotencyInProgressError(RuntimeError):
    pass


class PostgreSqlIdempotencyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def request_hash(payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()

    def get(
        self,
        idempotency_key: str,
    ) -> IdempotencyRecord | None:
        return self._session.get(
            IdempotencyRecord,
            idempotency_key,
        )

    def begin(
        self,
        *,
        idempotency_key: str,
        request_hash: str,
        expires_at: datetime | None = None,
    ) -> IdempotencyRecord:
        existing = self.get(idempotency_key)
        if existing is not None:
            self._validate_existing(
                existing=existing,
                request_hash=request_hash,
            )
            return existing

        record = IdempotencyRecord(
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            status_code="PROCESSING",
            expires_at=expires_at,
        )
        self._session.add(record)

        try:
            self._session.flush()
            return record
        except IntegrityError:
            self._session.rollback()
            existing = self.get(idempotency_key)
            if existing is None:
                raise
            self._validate_existing(
                existing=existing,
                request_hash=request_hash,
            )
            return existing

    def complete(
        self,
        *,
        idempotency_key: str,
        result_json: dict[str, Any],
    ) -> IdempotencyRecord:
        record = self._require(idempotency_key)
        record.status_code = "COMPLETED"
        record.result_json = result_json
        record.error_message = None
        self._session.flush()
        return record

    def fail(
        self,
        *,
        idempotency_key: str,
        error_message: str,
    ) -> IdempotencyRecord:
        record = self._require(idempotency_key)
        record.status_code = "FAILED"
        record.error_message = error_message
        self._session.flush()
        return record

    def execute_once(
        self,
        *,
        idempotency_key: str,
        payload: dict[str, Any],
        operation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        request_hash = self.request_hash(payload)
        record = self.begin(
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )

        if record.status_code == "COMPLETED":
            return record.result_json or {}

        if record.status_code == "PROCESSING" and record.created_at is not None:
            if record.result_json is None and record.idempotency_key == idempotency_key:
                # The row may have been inserted by this transaction or another worker.
                # Caller-level transaction boundaries determine whether execution proceeds.
                pass

        try:
            result = operation()
            self.complete(
                idempotency_key=idempotency_key,
                result_json=result,
            )
            return result
        except Exception as exc:
            self.fail(
                idempotency_key=idempotency_key,
                error_message=str(exc),
            )
            raise

    def _require(
        self,
        idempotency_key: str,
    ) -> IdempotencyRecord:
        record = self.get(idempotency_key)
        if record is None:
            raise LookupError(
                f"Idempotency record not found: {idempotency_key}"
            )
        return record

    @staticmethod
    def _validate_existing(
        *,
        existing: IdempotencyRecord,
        request_hash: str,
    ) -> None:
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError(
                "The same idempotency key was used with a different request."
            )
