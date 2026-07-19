from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from stock_platform.auth.deps import (
    AuthenticatedUser,
    get_auth_service,
    get_current_user,
)
from stock_platform.auth.schemas import (
    AuthUserResponse,
    AvailabilityResponse,
    ChangePasswordRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
)
from stock_platform.auth.service import AuthError, AuthService, user_view_dict
from stock_platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["Auth"],
)


def _token_response(pair, view) -> TokenResponse:
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        token_type=pair.token_type,
        expires_in=pair.expires_in,
        user=AuthUserResponse(**user_view_dict(view)),
    )


def _validation_detail(exc: ValueError) -> str:
    # Pydantic ValidationError 는 FastAPI가 처리. 여기선 AuthError/ValueError 메시지.
    return str(exc)


@router.post(
    "/signup",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
def signup(
    request: SignupRequest,
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
):
    try:
        pair, view = service.signup(
            name=request.name,
            username=request.username,
            email=str(request.email),
            password=request.password,
            password_confirm=request.password_confirm,
            terms_accepted=request.terms_accepted,
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
            detail=_validation_detail(exc),
        ) from exc
    return _token_response(pair, view)


@router.get("/check-username", response_model=AvailabilityResponse)
def check_username(
    username: str = Query(min_length=1, max_length=64),
    service: AuthService = Depends(get_auth_service),
):
    available = service.check_username_available(username)
    return AvailabilityResponse(
        available=available,
        field="username",
        value=username.strip().lower(),
    )


@router.get("/check-email", response_model=AvailabilityResponse)
def check_email(
    email: str = Query(min_length=3, max_length=255),
    service: AuthService = Depends(get_auth_service),
):
    available = service.check_email_available(email)
    return AvailabilityResponse(
        available=available,
        field="email",
        value=email.strip().lower(),
    )


@router.post("/login", response_model=TokenResponse)
def login(
    request: LoginRequest,
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
):
    try:
        pair, view = service.login(
            username=request.username,
            password=request.password,
        )
        session.commit()
    except AuthError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return _token_response(pair, view)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    request: RefreshRequest,
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
):
    try:
        pair, view = service.refresh(
            refresh_token=request.refresh_token,
        )
        session.commit()
    except AuthError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    return _token_response(pair, view)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: LogoutRequest,
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
):
    service.logout(refresh_token=request.refresh_token)
    session.commit()
    return None


@router.get("/me", response_model=AuthUserResponse)
def me(user: AuthenticatedUser = Depends(get_current_user)):
    return AuthUserResponse(
        id=str(user.user_id),
        username=user.username,
        email=getattr(user, "email", None),
        display_name=user.display_name,
        roles=user.roles,
        permissions=user.permissions,
    )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    request: ChangePasswordRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
):
    try:
        service.change_password(
            user_id=user.user_id,
            current_password=request.current_password,
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
    return None
