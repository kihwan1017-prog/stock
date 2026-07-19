from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.auth.rbac_repository import RbacRepository
from stock_platform.auth.rbac_service import (
    RbacService,
    permission_view_dict,
    role_view_dict,
)
from stock_platform.auth.schemas import (
    PermissionResponse,
    RolePermissionUpdateRequest,
    RoleResponse,
    UserRolesUpdateRequest,
)
from stock_platform.auth.service import AuthError
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/roles",
    tags=["Roles"],
)


def get_rbac_service(
    session: Session = Depends(get_db_session),
) -> RbacService:
    return RbacService(RbacRepository(session))


@router.get("", response_model=list[RoleResponse])
def list_roles(
    _: AuthenticatedUser = Depends(require_permission("roles:read")),
    service: RbacService = Depends(get_rbac_service),
):
    return [
        RoleResponse(**role_view_dict(item))
        for item in service.list_roles()
    ]


@router.get("/permissions", response_model=list[PermissionResponse])
def list_permissions(
    category: str | None = Query(default=None, max_length=32),
    _: AuthenticatedUser = Depends(require_permission("roles:read")),
    service: RbacService = Depends(get_rbac_service),
):
    return [
        PermissionResponse(**permission_view_dict(item))
        for item in service.list_permissions(category=category)
    ]


@router.get("/{role_id}", response_model=RoleResponse)
def get_role(
    role_id: int,
    _: AuthenticatedUser = Depends(require_permission("roles:read")),
    service: RbacService = Depends(get_rbac_service),
):
    try:
        view = service.get_role(role_id)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return RoleResponse(**role_view_dict(view))


@router.put("/{role_id}/permissions", response_model=RoleResponse)
def update_role_permissions(
    role_id: int,
    request: RolePermissionUpdateRequest,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_permission("roles:write")),
    service: RbacService = Depends(get_rbac_service),
):
    try:
        view = service.set_role_permissions(
            role_id,
            permission_codes=request.permissions,
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
    return RoleResponse(**role_view_dict(view))


@router.put("/users/{user_id}", response_model=dict)
def update_user_roles(
    user_id: int,
    request: UserRolesUpdateRequest,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_permission("roles:write")),
    service: RbacService = Depends(get_rbac_service),
):
    try:
        roles = service.set_user_roles(
            user_id,
            role_codes=request.roles,
        )
        # JSONB 캐시도 동기화
        from stock_platform.auth.repository import AuthRepository

        repo = AuthRepository(session)
        user = repo.get_by_id(user_id)
        if user is None:
            raise AuthError("회원을 찾을 수 없습니다.")
        repo.update_user(user, roles=roles)
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
    return {"user_id": user_id, "roles": roles}
