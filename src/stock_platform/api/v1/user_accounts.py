"""회원 전용 계좌 CRUD API — STEP65."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.database.session import get_db_session
from stock_platform.trading.user_account_service import (
    UserAccountError,
    UserAccountService,
)


router = APIRouter(
    prefix="/api/v1/user/accounts",
    tags=["User Accounts"],
)


class CreateUserAccountRequest(BaseModel):
    account_type: str = Field(
        min_length=1,
        max_length=20,
        description="PAPER | KIWOOM | UPBIT",
    )
    account_name: str | None = Field(
        default=None,
        max_length=100,
        description="별칭 / Paper 계좌명",
    )
    initial_cash: Decimal | None = Field(
        default=None,
        gt=0,
        description="PAPER 전용 초기 현금",
    )
    currency_code: str = Field(default="KRW", max_length=10)
    # Broker 연결 시에만 수신 — 응답·DB 원문 저장 금지
    account_number: str | None = Field(
        default=None,
        max_length=64,
        description="Broker 계좌번호 (해시·마스킹만 저장)",
    )
    is_default: bool = False


class UpdateUserAccountRequest(BaseModel):
    account_name: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None
    account_type: str | None = Field(
        default=None,
        max_length=20,
        description="ID 충돌 시 PAPER/KIWOOM/UPBIT 구분",
    )


def _service(session: Session) -> UserAccountService:
    return UserAccountService(session)


def _http_error(exc: UserAccountError) -> HTTPException:
    message = str(exc)
    code = (
        status.HTTP_404_NOT_FOUND
        if "찾을 수 없" in message
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=message)


@router.get("")
def list_user_accounts(
    default: bool = Query(
        False,
        description="기본 계좌만 조회",
    ),
    include_inactive: bool = Query(False),
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    """로그인 사용자 본인 계좌만 반환. user_id 는 JWT 에서만 결정."""

    rows = _service(session).list_accounts(
        user.user_id,
        default_only=default,
        include_inactive=include_inactive,
    )
    return {
        "items": [row.as_dict() for row in rows],
        "total": len(rows),
    }


@router.post("")
def create_user_account(
    request: CreateUserAccountRequest,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        view = _service(session).create_account(
            user.user_id,
            account_type=request.account_type,
            account_name=request.account_name,
            initial_cash=request.initial_cash,
            currency_code=request.currency_code,
            account_number=request.account_number,
            is_default=request.is_default,
        )
    except UserAccountError as exc:
        raise _http_error(exc) from exc
    return view.as_dict()


@router.get("/{account_id}")
def get_user_account(
    account_id: int,
    account_type: str | None = Query(None),
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        view = _service(session).get_account(
            user.user_id,
            account_id,
            account_type=account_type,
        )
    except UserAccountError as exc:
        raise _http_error(exc) from exc
    return view.as_dict()


@router.patch("/{account_id}")
def update_user_account(
    account_id: int,
    request: UpdateUserAccountRequest,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        view = _service(session).update_account(
            user.user_id,
            account_id,
            account_type=request.account_type,
            account_name=request.account_name,
            is_active=request.is_active,
        )
    except UserAccountError as exc:
        raise _http_error(exc) from exc
    return view.as_dict()


@router.delete("/{account_id}")
def delete_user_account(
    account_id: int,
    account_type: str | None = Query(None),
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        return _service(session).delete_account(
            user.user_id,
            account_id,
            account_type=account_type,
        )
    except UserAccountError as exc:
        raise _http_error(exc) from exc


@router.post("/{account_id}/set-default")
def set_default_user_account(
    account_id: int,
    account_type: str | None = Query(None),
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        view = _service(session).set_default(
            user.user_id,
            account_id,
            account_type=account_type,
        )
    except UserAccountError as exc:
        raise _http_error(exc) from exc
    return view.as_dict()


@router.post("/{account_id}/connect")
def connect_user_account(
    account_id: int,
    account_type: str | None = Query(None),
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        view = _service(session).connect(
            user.user_id,
            account_id,
            account_type=account_type,
        )
    except UserAccountError as exc:
        raise _http_error(exc) from exc
    return view.as_dict()


@router.post("/{account_id}/disconnect")
def disconnect_user_account(
    account_id: int,
    account_type: str | None = Query(None),
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        view = _service(session).disconnect(
            user.user_id,
            account_id,
            account_type=account_type,
        )
    except UserAccountError as exc:
        raise _http_error(exc) from exc
    return view.as_dict()


@router.post("/{account_id}/sync")
def sync_user_account(
    account_id: int,
    account_type: str | None = Query(None),
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    """
    회원 스코프 동기화 메타 갱신.
    키움 OpenAPI 실동기화는 서버 공용 credential 을 사용하며
    admin 전용 POST /broker/kiwoom/account/sync 를 참고한다.
    """

    try:
        view = _service(session).sync(
            user.user_id,
            account_id,
            account_type=account_type,
        )
    except UserAccountError as exc:
        raise _http_error(exc) from exc
    return {
        **view.as_dict(),
        "sync_note": (
            "Broker 실동기화는 서버 공용 Kiwoom 설정을 사용합니다. "
            "회원별 Client Secret 은 저장·노출하지 않습니다."
        ),
    }
