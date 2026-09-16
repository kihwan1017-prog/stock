from __future__ import annotations

from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
)
from stock_platform.auth.account_ownership import (
    assert_paper_account_access,
)
from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_admin_user,
    require_permission,
)
from stock_platform.database.session import get_db_session
from stock_platform.trading.account_models import PaperAccount
from stock_platform.trading.account_repository import (
    PaperAccountRepository,
)
from stock_platform.trading.account_service import (
    PaperAccountError,
    PaperAccountService,
)
from stock_platform.trading.models import OrderSide


router = APIRouter(
    prefix="/api/v1/paper-accounts",
    tags=["Paper Accounts"],
)


class CreatePaperAccountRequest(BaseModel):
    account_name: str = Field(
        min_length=1,
        max_length=100,
    )
    initial_cash: Decimal = Field(gt=0)
    currency_code: str = Field(
        default="KRW",
        min_length=1,
        max_length=10,
    )


class UpdatePaperAccountRequest(BaseModel):
    """부분 수정 — 전달된 필드만 변경. 모델에 없는 설명/전략/위험 필드는 미포함."""

    account_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
    is_active: bool | None = None
    is_default: bool | None = None
    initial_cash: Decimal | None = Field(default=None, gt=0)


class ApplyFillRequest(BaseModel):
    exchange_code: str = Field(
        min_length=1,
        max_length=20,
    )
    symbol: str = Field(
        min_length=1,
        max_length=30,
    )
    side: OrderSide
    quantity: Decimal = Field(gt=0)
    fill_price: Decimal = Field(gt=0)
    order_id: int | None = Field(
        default=None,
        gt=0,
    )


class AccountValuationRequest(BaseModel):
    prices: dict[str, Decimal]


def _service(session: Session) -> PaperAccountService:
    return PaperAccountService(
        PaperAccountRepository(session)
    )


def _account_dict(
    account: PaperAccount,
    *,
    repo: PaperAccountRepository | None = None,
    include_edit_meta: bool = False,
) -> dict:
    payload: dict = {
        "account_id": account.account_id,
        "user_id": account.user_id,
        "account_name": account.account_name,
        "currency_code": account.currency_code,
        "initial_cash": account.initial_cash,
        "available_cash": account.available_cash,
        "realized_profit_loss": account.realized_profit_loss,
        "is_default": bool(account.is_default),
        "is_active": bool(account.is_active),
        "deleted_at": account.deleted_at,
        "broker_code": account.broker_code,
        "exchange_code": account.exchange_code,
        "created_at": account.created_at,
        "updated_at": account.updated_at,
    }
    if include_edit_meta and repo is not None:
        has_history = repo.has_trading_activity(int(account.account_id))
        payload["has_trading_history"] = has_history
        payload["can_edit_initial_cash"] = not has_history
    return payload


def _ensure_my_account(
    user: AuthenticatedUser,
    session: Session,
) -> PaperAccount:
    """내 Paper 계좌 — 없으면 lazy 생성 (기본 계좌 1개)."""

    from stock_platform.trading.user_account_service import (
        UserAccountError,
        UserAccountService,
    )

    try:
        view = UserAccountService(session).ensure_default_paper(
            user.user_id
        )
    except UserAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    account = PaperAccountRepository(session).get_account(
        view.account_id
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="기본 Paper 계좌를 준비하지 못했습니다.",
        )
    return account


@router.get("/me")
def get_my_paper_account(
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    """로그인 사용자 기본 Paper 계좌 (없으면 생성)."""

    return _account_dict(_ensure_my_account(user, session))


@router.get("")
def list_paper_accounts(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    """모의 계좌 목록 — admin 전체, 그 외 본인 소유만."""

    repo = PaperAccountRepository(session)
    if user.is_admin:
        rows = repo.list_accounts(limit=limit, offset=offset)
    else:
        rows = repo.list_accounts(
            limit=limit,
            offset=offset,
            user_id=user.user_id,
        )
    return [_account_dict(row) for row in rows]


@router.get("/{account_id}")
def get_paper_account(
    account_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    account = assert_paper_account_access(
        user, account_id, session
    )
    repo = PaperAccountRepository(session)
    return _account_dict(
        account,
        repo=repo,
        include_edit_meta=True,
    )


@router.post("")
def create_paper_account(
    request: CreatePaperAccountRequest,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    from stock_platform.trading.user_account_service import (
        UserAccountError,
        UserAccountService,
    )

    try:
        view = UserAccountService(session).create_account(
            user.user_id,
            account_type="PAPER",
            account_name=request.account_name,
            initial_cash=request.initial_cash,
            currency_code=request.currency_code,
        )
    except UserAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    account = assert_paper_account_access(
        user, view.account_id, session
    )
    return _account_dict(
        account,
        repo=PaperAccountRepository(session),
        include_edit_meta=True,
    )


@router.patch("/{account_id}")
def update_paper_account(
    account_id: int,
    request: UpdatePaperAccountRequest,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """
    Soft-deleted 계좌 수정 불가.
    소유권: assert_paper_account_access (admin 전체 / 그 외 본인).
    initial_cash: 주문·체결·보유 이력이 없을 때만.
    """

    # IDOR 차단 — DB 소유권 재검증
    assert_paper_account_access(user, account_id, session)

    fields_set = set(request.model_dump(exclude_unset=True).keys())
    try:
        account, changes = _service(session).update_account(
            account_id,
            account_name=request.account_name,
            is_active=request.is_active,
            is_default=request.is_default,
            initial_cash=request.initial_cash,
            fields_set=fields_set,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PaperAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if changes:
        audit.record(
            event_type="PAPER_ACCOUNT_UPDATE",
            actor=user.username,
            detail={
                "actor_user_id": user.user_id,
                "account_id": account_id,
                "changed_fields": [c["field"] for c in changes],
                "changes": changes,
            },
        )
        session.commit()

    return _account_dict(
        account,
        repo=PaperAccountRepository(session),
        include_edit_meta=True,
    )


@router.delete("/{account_id}")
def delete_paper_account(
    account_id: int,
    actor: AuthenticatedUser = Depends(require_admin_user),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """
    Soft Delete (deleted_at) — 관리자 전용.

    - Hard Delete 금지 (주문/체결 이력이 있어도 Soft Delete만)
    - 목록에서는 deleted_at IS NULL 만 노출
    """

    try:
        result = _service(session).soft_delete_account(
            account_id,
            allow_default=True,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PaperAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    audit.record(
        event_type="PAPER_ACCOUNT_SOFT_DELETE",
        actor=actor.username,
        detail={
            "account_id": result["account_id"],
            "mode": result["mode"],
            "has_trading_history": result["has_trading_history"],
            "hard_delete_allowed": False,
            "deleted_at": result.get("deleted_at"),
        },
    )
    session.commit()
    return result


@router.post("/{account_id}/fills")
def apply_paper_fill(
    account_id: int,
    request: ApplyFillRequest,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    assert_paper_account_access(user, account_id, session)
    try:
        return _service(session).apply_fill(
            account_id=account_id,
            exchange_code=request.exchange_code,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            fill_price=request.fill_price,
            order_id=request.order_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PaperAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/{account_id}/positions")
def list_paper_positions(
    account_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    assert_paper_account_access(user, account_id, session)
    return PaperAccountRepository(session).list_positions(
        account_id=account_id
    )


@router.post("/{account_id}/valuation")
def value_paper_account(
    account_id: int,
    request: AccountValuationRequest,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    assert_paper_account_access(user, account_id, session)
    try:
        return _service(session).value_account(
            account_id=account_id,
            prices={
                key.upper(): value
                for key, value in request.prices.items()
            },
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PaperAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
