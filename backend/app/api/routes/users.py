from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.routes.auth import clear_auth_cookies, set_auth_cookies
from app.core import rate_limit
from app.core.config import get_settings
from app.core.errors import InvalidRequestError
from app.db.database import get_db
from app.db.models import User
from app.schemas.user import (
    AuthResponse,
    ChangePasswordRequest,
    DeleteAccountRequest,
    PreferencesUpdate,
    ProfileUpdate,
    UserOut,
)
from app.services import audit_service
from app.services.auth_service import AuthService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut, summary="The signed-in user")
async def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me/profile", response_model=UserOut, summary="Update profile fields")
async def update_profile(body: ProfileUpdate, request: Request,
                         user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    changes = body.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(user.profile, field, value)
    await audit_service.record(db, "user.profile_update", user_id=user.id,
                               ip_address=rate_limit.client_ip(request),
                               details={"fields": sorted(changes)})
    await db.commit()
    return user


@router.put("/me/preferences", response_model=UserOut, summary="Replace travel preferences")
async def update_preferences(body: PreferencesUpdate, request: Request,
                             user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    prefs = user.preferences
    data = body.model_dump()
    existing = {p["airline"].lower(): p["number"] for p in prefs.frequent_flyer_programs or []}
    programs = []
    for program in data["frequent_flyer_programs"]:
        number = program["number"] or existing.get(program["airline"].lower())
        if not number:
            raise InvalidRequestError(
                f"Enter the membership number for {program['airline']}."
            )
        programs.append({"airline": program["airline"], "number": number})
    data["frequent_flyer_programs"] = programs
    for field, value in data.items():
        setattr(prefs, field, value)
    await audit_service.record(db, "user.preferences_update", user_id=user.id,
                               ip_address=rate_limit.client_ip(request))
    await db.commit()
    return user


@router.delete("/me", status_code=204,
               summary="Delete your account, documents, conversations and bookings")
async def delete_account(body: DeleteAccountRequest, request: Request, response: Response,
                         user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    """Needs your password. Upcoming bookings must be cancelled first. The anonymised audit
    log is kept."""
    ip = rate_limit.client_ip(request)
    await rate_limit.enforce("auth", ip, get_settings().AUTH_RATE_LIMIT_PER_MINUTE)
    await AuthService(db).delete_account(user, body.password, ip)
    clear_auth_cookies(response)
    response.status_code = 204


@router.post("/me/password", response_model=AuthResponse,
             summary="Change password (signs out other devices)")
async def change_password(body: ChangePasswordRequest, request: Request, response: Response,
                          user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    ip = rate_limit.client_ip(request)
    await rate_limit.enforce("auth", ip, get_settings().AUTH_RATE_LIMIT_PER_MINUTE)
    issued = await AuthService(db).change_password(user, body.current_password,
                                                   body.new_password, ip)
    csrf = set_auth_cookies(response, issued)
    return AuthResponse(user=UserOut.model_validate(user), access_token=issued.access_token,
                        expires_at=issued.expires_at, csrf_token=csrf)
