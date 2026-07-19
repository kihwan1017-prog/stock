from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.auth.rbac_repository import RbacRepository
from stock_platform.auth.repository import AuthRepository, SortField, SortOrder
from stock_platform.auth.schemas import (
    MemberCreateRequest,
    MemberListResponse,
    MemberResetPasswordRequest,
    MemberResetPasswordResponse,
    MemberResponse,
    MemberUpdateRequest,
)
from stock_platform.auth.service import AuthError
from stock_platform.auth.user_admin_service import (
    UserAdminService,
    member_view_dict,
)
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/users",
    tags=["Users"],
)


def get_user_admin_service(
    session: Session = Depends(get_db_session),
) -> UserAdminService:
    return UserAdminService(
        AuthRepository(session),
        RbacRepository(session),
    )


def _member_response(view) -> MemberResponse:
    return MemberResponse(**member_view_dict(view))


@router.get("", response_model=MemberListResponse)
def list_users(
    q: str | None = Query(default=None, max_length=100),
    is_active: bool | None = Query(default=None),
    role: str | None = Query(default=None, max_length=32),
    include_deleted: bool = Query(default=False),
    sort_by: SortField = Query(default="created_at"),
    sort_order: SortOrder = Query(default="desc"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: AuthenticatedUser = Depends(require_permission("users:read")),
    service: UserAdminService = Depends(get_user_admin_service),
):
    items, total = service.list_members(
        q=q,
        is_active=is_active,
        role=role,
        include_deleted=include_deleted,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )
    return MemberListResponse(
        items=[_member_response(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    request: MemberCreateRequest,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_permission("users:write")),
    service: UserAdminService = Depends(get_user_admin_service),
):
    try:
        view = service.create_member(
            username=request.username,
            password=request.password,
            display_name=request.display_name,
            roles=request.roles,
            is_active=request.is_active,
            email=request.email,
        )
        session.commit()
    except AuthError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return _member_response(view)


@router.get("/{user_id}", response_model=MemberResponse)
def get_user(
    user_id: int,
    include_deleted: bool = Query(default=False),
    _: AuthenticatedUser = Depends(require_permission("users:read")),
    service: UserAdminService = Depends(get_user_admin_service),
):
    try:
        view = service.get_member(
            user_id,
            include_deleted=include_deleted,
        )
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return _member_response(view)


@router.put("/{user_id}", response_model=MemberResponse)
def update_user(
    user_id: int,
    request: MemberUpdateRequest,
    actor: AuthenticatedUser = Depends(require_permission("users:write")),
    session: Session = Depends(get_db_session),
    service: UserAdminService = Depends(get_user_admin_service),
):
    try:
        view = service.update_member(
            user_id,
            display_name=request.display_name,
            email=request.email,
            roles=request.roles,
            is_active=request.is_active,
            actor_user_id=actor.user_id,
        )
        session.commit()
    except AuthError as exc:
        session.rollback()
        status_code = (
            status.HTTP_404_NOT_FOUND
            if "찾을 수 없" in str(exc)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(
            status_code=status_code,
            detail=str(exc),
        ) from exc
    return _member_response(view)


@router.delete("/{user_id}", response_model=MemberResponse)
def delete_user(
    user_id: int,
    actor: AuthenticatedUser = Depends(require_permission("users:delete")),
    session: Session = Depends(get_db_session),
    service: UserAdminService = Depends(get_user_admin_service),
):
    try:
        view = service.soft_delete_member(
            user_id,
            actor_user_id=actor.user_id,
        )
        session.commit()
    except AuthError as exc:
        session.rollback()
        status_code = (
            status.HTTP_404_NOT_FOUND
            if "찾을 수 없" in str(exc)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(
            status_code=status_code,
            detail=str(exc),
        ) from exc
    return _member_response(view)


@router.post("/{user_id}/activate", response_model=MemberResponse)
def activate_user(
    user_id: int,
    actor: AuthenticatedUser = Depends(require_permission("users:write")),
    session: Session = Depends(get_db_session),
    service: UserAdminService = Depends(get_user_admin_service),
):
    try:
        view = service.set_active(
            user_id,
            is_active=True,
            actor_user_id=actor.user_id,
        )
        session.commit()
    except AuthError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return _member_response(view)


@router.post("/{user_id}/deactivate", response_model=MemberResponse)
def deactivate_user(
    user_id: int,
    actor: AuthenticatedUser = Depends(require_permission("users:write")),
    session: Session = Depends(get_db_session),
    service: UserAdminService = Depends(get_user_admin_service),
):
    try:
        view = service.set_active(
            user_id,
            is_active=False,
            actor_user_id=actor.user_id,
        )
        session.commit()
    except AuthError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return _member_response(view)


@router.post(
    "/{user_id}/reset-password",
    response_model=MemberResetPasswordResponse,
)
def reset_user_password(
    user_id: int,
    request: MemberResetPasswordRequest,
    _: AuthenticatedUser = Depends(require_permission("users:write")),
    session: Session = Depends(get_db_session),
    service: UserAdminService = Depends(get_user_admin_service),
):
    try:
        view, temporary = service.reset_password(
            user_id,
            new_password=request.new_password,
        )
        session.commit()
    except AuthError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return MemberResetPasswordResponse(
        user=_member_response(view),
        temporary_password=temporary,
    )
