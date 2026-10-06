from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ACCESS_COOKIE, CSRF_COOKIE, get_current_user
from app.core import rate_limit
from app.core.config import get_settings
from app.core.security import new_csrf_token
from app.db.database import get_db
from app.db.models import User
from app.schemas.user import AuthResponse, LoginRequest, RegisterRequest, UserOut
from app.services.auth_service import AuthService, IssuedToken

router = APIRouter(prefix="/auth", tags=["auth"])


def _limit(request: Request) -> str:
    ip = rate_limit.client_ip(request)
    rate_limit.enforce("auth", ip, get_settings().AUTH_RATE_LIMIT_PER_MINUTE)
    return ip


def set_auth_cookies(response: Response, issued: IssuedToken) -> str:
    settings = get_settings()
    csrf = new_csrf_token()
    for name, value, httponly in (
        (ACCESS_COOKIE, issued.access_token, True),
        # Readable by the frontend so it can echo it in the X-CSRF-Token header.
        (CSRF_COOKIE, csrf, False),
    ):
        response.set_cookie(name, value, httponly=httponly, secure=settings.cookie_secure,
                            samesite="lax", path="/", domain=settings.COOKIE_DOMAIN,
                            max_age=settings.ACCESS_TOKEN_MINUTES * 60)
    return csrf


def clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    for name in (ACCESS_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", domain=settings.COOKIE_DOMAIN)


def _auth_response(response: Response, issued: IssuedToken) -> AuthResponse:
    csrf = set_auth_cookies(response, issued)
    return AuthResponse(
        user=UserOut.model_validate(issued.user),
        access_token=issued.access_token,
        expires_at=issued.expires_at,
        csrf_token=csrf,
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED,
             summary="Create an account and sign in")
async def register(body: RegisterRequest, request: Request, response: Response,
                   db: AsyncSession = Depends(get_db)):
    ip = _limit(request)
    issued = await AuthService(db).register(body.email, body.password, body.full_name, ip)
    return _auth_response(response, issued)


@router.post("/login", response_model=AuthResponse, summary="Sign in with email and password")
async def login(body: LoginRequest, request: Request, response: Response,
                db: AsyncSession = Depends(get_db)):
    ip = _limit(request)
    issued = await AuthService(db).login(body.email, body.password, ip)
    return _auth_response(response, issued)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT,
             summary="Sign out of this browser")
async def logout(response: Response):
    clear_auth_cookies(response)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT,
             summary="Sign out of every device")
async def logout_all(request: Request, response: Response, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    await AuthService(db).logout_everywhere(user, rate_limit.client_ip(request))
    clear_auth_cookies(response)
