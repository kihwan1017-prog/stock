from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
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
    GoogleCompleteRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
)
from stock_platform.auth.service import AuthError, AuthService, user_view_dict
from stock_platform.auth.session_meta import session_meta_from_request
from stock_platform.common.rate_limit import enforce_rate_limit
from stock_platform.common.settings import Settings, get_settings
from stock_platform.database.session import get_db_session
from stock_platform.api.deps_admin import AuditLogService, get_audit_service
from stock_platform.common.security_mask import mask_secret
from stock_platform.auth.refresh_cookie import (
    clear_refresh_cookie,
    read_refresh_token,
    set_refresh_cookie,
)

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["Auth"],
)


def _token_response(pair, view, response: Response | None = None) -> TokenResponse:
    user = AuthUserResponse(**user_view_dict(view))
    if response is not None:
        set_refresh_cookie(response, pair.refresh_token)
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        token_type=pair.token_type,
        expires_in=pair.expires_in,
        user=user,
        default_route=view.default_route,
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
    response: Response,
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
):
    # RC1 — 운영에서는 공개 가입 차단 (Admin Users API로 생성)
    if get_settings().is_production_env:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Public signup is disabled in production. "
                "Create users via Admin API."
            ),
        )
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
    return _token_response(pair, view, response)


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
    http_request: Request,
    response: Response,
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
    audit: AuditLogService = Depends(get_audit_service),
):
    enforce_rate_limit(
        http_request,
        scope="auth_login",
        limit=20,
        window_seconds=60,
    )
    try:
        pair, view = service.login(
            username=request.username,
            password=request.password,
            session_meta=session_meta_from_request(http_request),
        )
        audit.record(
            event_type="AUTH_LOGIN_SUCCESS",
            actor=view.username,
            detail={"username": view.username},
        )
        session.commit()
    except AuthError as exc:
        session.rollback()
        try:
            AuditLogService(session).record(
                event_type="AUTH_LOGIN_FAILURE",
                actor="anonymous",
                detail={
                    "username": mask_secret(
                        request.username.strip(), visible=2
                    ),
                },
            )
            session.commit()
        except Exception:
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
    return _token_response(pair, view, response)


@router.get("/google/status")
def google_oauth_status(
    settings: Settings = Depends(get_settings),
):
    """FE용 — Google 로그인 버튼 노출 여부 (secret 미포함)."""

    configured = bool(
        settings.google_oauth_enabled
        and settings.google_oauth_client_id.strip()
        and settings.google_oauth_client_secret.strip()
        and settings.google_oauth_redirect_uri.strip()
        and settings.google_oauth_frontend_complete_url.strip()
    )
    return {"enabled": configured, "provider": "google"}


@router.get("/google/login")
def google_oauth_login(
    next: str | None = Query(default=None, max_length=512),
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
):
    """Browser redirect → Google authorize URL."""

    from stock_platform.auth.google_oauth import GoogleOAuthService
    from urllib.parse import quote

    oauth = GoogleOAuthService(session, settings, service)
    try:
        url = oauth.build_authorization_url(next_path=next)
        session.commit()
    except AuthError as exc:
        session.rollback()
        # FE로 오류 전달 (open redirect 방지: complete URL만 허용)
        complete = settings.google_oauth_frontend_complete_url.strip()
        if complete:
            from fastapi.responses import RedirectResponse

            return RedirectResponse(
                url=f"{complete}?error={quote(str(exc))}",
                status_code=status.HTTP_302_FOUND,
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/google/callback")
def google_oauth_callback(
    http_request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
    audit: AuditLogService = Depends(get_audit_service),
):
    """Google redirect → FE handoff (토큰은 query에 넣지 않음)."""

    from urllib.parse import quote

    from fastapi.responses import RedirectResponse

    from stock_platform.auth.google_oauth import GoogleOAuthService

    complete = settings.google_oauth_frontend_complete_url.strip()
    if not complete:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth frontend complete URL이 설정되지 않았습니다.",
        )

    if error:
        return RedirectResponse(
            url=f"{complete}?error={quote('Google 인증이 취소되었거나 실패했습니다.')}",
            status_code=status.HTTP_302_FOUND,
        )

    oauth = GoogleOAuthService(session, settings, service)
    try:
        redirect_url = oauth.complete_callback(
            code=code or "",
            state=state or "",
            session_meta=session_meta_from_request(http_request),
        )
        audit.record(
            event_type="AUTH_GOOGLE_LOGIN_SUCCESS",
            actor="google_oauth",
            detail={"provider": "google"},
        )
        session.commit()
    except AuthError as exc:
        session.rollback()
        try:
            AuditLogService(session).record(
                event_type="AUTH_GOOGLE_LOGIN_FAILURE",
                actor="anonymous",
                detail={"provider": "google"},
            )
            session.commit()
        except Exception:
            session.rollback()
        return RedirectResponse(
            url=f"{complete}?error={quote(str(exc))}",
            status_code=status.HTTP_302_FOUND,
        )
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)


@router.post("/google/complete", response_model=TokenResponse)
def google_oauth_complete(
    body: GoogleCompleteRequest,
    http_request: Request,
    response: Response,
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
):
    """FE one-time handoff code → 기존 TokenResponse (sessionStorage 저장)."""

    from stock_platform.auth.google_oauth import GoogleOAuthService

    oauth = GoogleOAuthService(session, settings, service)
    try:
        pair, view, _next = oauth.exchange_handoff(
            code=body.code,
            session_meta=session_meta_from_request(http_request),
        )
        session.commit()
    except AuthError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    return _token_response(pair, view, response)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    request: RefreshRequest,
    http_request: Request,
    response: Response,
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
):
    enforce_rate_limit(
        http_request,
        scope="auth_refresh",
        limit=60,
        window_seconds=60,
    )
    token = read_refresh_token(http_request, request.refresh_token)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh 토큰이 필요합니다.",
        )
    try:
        pair, view = service.refresh(
            refresh_token=token,
            session_meta=session_meta_from_request(http_request),
        )
        session.commit()
    except AuthError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    return _token_response(pair, view, response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: LogoutRequest,
    http_request: Request,
    response: Response,
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
    audit: AuditLogService = Depends(get_audit_service),
):
    token = read_refresh_token(http_request, request.refresh_token)
    service.logout(refresh_token=token)
    clear_refresh_cookie(response)
    try:
        audit.record(
            event_type="AUTH_LOGOUT",
            actor="anonymous",
            detail={},
        )
    except Exception:
        pass
    session.commit()
    return None


@router.get("/me", response_model=AuthUserResponse)
def me(
    user: AuthenticatedUser = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    """DB 기준 최신 사용자·역할·권한·default_route."""

    view = service.get_user(user.user_id)
    return AuthUserResponse(**user_view_dict(view))


@router.post("/onboarding/complete", response_model=AuthUserResponse)
def complete_onboarding(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
    audit: AuditLogService = Depends(get_audit_service),
):
    try:
        view = service.complete_onboarding(user_id=user.user_id)
        audit.record(
            event_type="AUTH_ONBOARDING_COMPLETE",
            actor=user.username,
            detail={"user_id": user.user_id},
        )
        session.commit()
    except AuthError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return AuthUserResponse(**user_view_dict(view))


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    request: ChangePasswordRequest,
    http_request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    service: AuthService = Depends(get_auth_service),
    audit: AuditLogService = Depends(get_audit_service),
):
    enforce_rate_limit(
        http_request,
        scope="auth_change_password",
        limit=10,
        window_seconds=300,
    )
    try:
        service.change_password(
            user_id=user.user_id,
            current_password=request.current_password,
            new_password=request.new_password,
        )
        audit.record(
            event_type="AUTH_PASSWORD_CHANGED",
            actor=user.username,
            detail={"user_id": user.user_id},
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
