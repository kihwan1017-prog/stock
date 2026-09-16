"""Kiwoom Credential ↔ UBA connection alignment (K_ONLY · diagnostic).

공통 Credential schema / UBA 모델 WRITE 없음.
실 secret 노출 금지 · LIVE 활성화 금지.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

MismatchCode = Literal[
    "NO_CREDENTIAL_ROW",
    "CREDENTIAL_NOT_LINKED",
    "CREDENTIAL_NOT_VERIFIED",
    "UBA_CONNECTION_STALE",
    "MOCK_CONNECTION_WITHOUT_CREDENTIAL",
    "LEGACY_STATE",
    "UBA_INACTIVE",
    "UBA_MISSING",
    "OTHER",
]


@dataclass(frozen=True, slots=True)
class KiwoomCredentialAlignmentView:
    """민감값 없는 Kiwoom credential/UBA 정렬 스냅샷."""

    user_broker_account_id: int
    user_id: int | None
    broker_code: str
    is_active: bool
    connection_status: str
    credential_linked: bool
    credential_active: bool
    verification_status: str | None
    masked_identifier: str | None
    last_verified_at_iso: str | None
    kiwoom_use_mock: bool
    mismatches: tuple[MismatchCode, ...]
    mock_ready: bool
    real_credential_ready: bool
    recommended_connection_status: str | None


def _mask_secret(value: str | None) -> str:
    if not value:
        return ""
    text = str(value)
    if len(text) <= 4:
        return "****"
    return f"{text[:2]}***{text[-2:]}"


def mask_kiwoom_credential_fields(payload: dict[str, Any] | None) -> dict[str, Any]:
    """로그/리포트용 — secret 필드 마스킹."""

    if not payload:
        return {}
    out: dict[str, Any] = {}
    secret_keys = {
        "app_key",
        "secret_key",
        "appsecret",
        "access_token",
        "refresh_token",
        "token",
        "password",
    }
    for key, val in payload.items():
        lk = str(key).lower()
        if lk in secret_keys or "secret" in lk or "token" in lk:
            out[key] = _mask_secret(str(val) if val is not None else None)
        else:
            out[key] = val
    return out


def classify_kiwoom_alignment(
    *,
    uba: Any | None,
    credential: Any | None,
    kiwoom_use_mock: bool,
) -> KiwoomCredentialAlignmentView:
    """UBA + credential entity(또는 None)로 MOCK/REAL readiness 판정."""

    if uba is None:
        return KiwoomCredentialAlignmentView(
            user_broker_account_id=0,
            user_id=None,
            broker_code="KIWOOM",
            is_active=False,
            connection_status="",
            credential_linked=False,
            credential_active=False,
            verification_status=None,
            masked_identifier=None,
            last_verified_at_iso=None,
            kiwoom_use_mock=bool(kiwoom_use_mock),
            mismatches=("UBA_MISSING",),
            mock_ready=bool(kiwoom_use_mock),
            real_credential_ready=False,
            recommended_connection_status="DISCONNECTED",
        )

    uba_id = int(getattr(uba, "user_broker_account_id"))
    user_id = getattr(uba, "user_id", None)
    conn = str(getattr(uba, "connection_status", "") or "")
    active = bool(getattr(uba, "is_active", False))
    mismatches: list[MismatchCode] = []

    linked = credential is not None
    cred_active = bool(getattr(credential, "is_active", False)) if linked else False
    revoked = getattr(credential, "revoked_at", None) is not None if linked else False
    if linked and revoked:
        cred_active = False
    verification = (
        str(getattr(credential, "verification_status", "") or "").upper()
        if linked
        else None
    )
    masked = getattr(credential, "masked_identifier", None) if linked else None
    last_verified = getattr(credential, "last_verified_at", None) if linked else None
    last_iso = last_verified.isoformat() if last_verified is not None else None

    if not linked or not cred_active:
        mismatches.append("NO_CREDENTIAL_ROW")
    elif verification != "VERIFIED":
        mismatches.append("CREDENTIAL_NOT_VERIFIED")

    if not active:
        mismatches.append("UBA_INACTIVE")

    conn_u = conn.upper()
    if conn_u in {"CONNECTED", "VERIFIED"} and (
        not linked or not cred_active or verification != "VERIFIED"
    ):
        if kiwoom_use_mock:
            mismatches.append("MOCK_CONNECTION_WITHOUT_CREDENTIAL")
        else:
            mismatches.append("UBA_CONNECTION_STALE")

    # MOCK: 시스템 mock 플래그면 credential 없이도 mock 경로 ready
    mock_ready = bool(kiwoom_use_mock) and active
    real_ready = bool(
        active
        and linked
        and cred_active
        and verification == "VERIFIED"
        and conn_u in {"CONNECTED", "VERIFIED"}
    )

    recommended: str | None = None
    if real_ready:
        recommended = "CONNECTED"
    elif linked and cred_active and verification == "VERIFIED":
        recommended = "CONNECTED"  # verify 성공 후 UBA 반영 기대
    elif linked and verification and verification not in {"VERIFIED"}:
        recommended = "CREDENTIAL_FAILED" if verification == "FAILED" else "CREDENTIAL_PENDING"
    elif not linked:
        recommended = "DISCONNECTED"

    return KiwoomCredentialAlignmentView(
        user_broker_account_id=uba_id,
        user_id=int(user_id) if user_id is not None else None,
        broker_code=str(getattr(uba, "broker_code", "KIWOOM") or "KIWOOM").upper(),
        is_active=active,
        connection_status=conn,
        credential_linked=linked,
        credential_active=cred_active,
        verification_status=verification,
        masked_identifier=str(masked) if masked else None,
        last_verified_at_iso=last_iso,
        kiwoom_use_mock=bool(kiwoom_use_mock),
        mismatches=tuple(dict.fromkeys(mismatches)),
        mock_ready=mock_ready,
        real_credential_ready=real_ready,
        recommended_connection_status=recommended,
    )


def assert_kiwoom_real_credential_ready(view: KiwoomCredentialAlignmentView) -> None:
    """REAL LIVE candidate gate — 실패 시 ValueError (비밀 미포함)."""

    if view.real_credential_ready:
        return
    codes = ",".join(view.mismatches) or "NOT_READY"
    raise ValueError(
        f"KIWOOM_REAL_CREDENTIAL_NOT_READY uba={view.user_broker_account_id} "
        f"codes={codes}"
    )
