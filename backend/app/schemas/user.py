import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

from app.core.logging import mask
from app.db.models import CabinClass, Role
from app.schemas.common import UtcDatetime

IataAirport = Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{3}$", to_upper=True,
                                               strip_whitespace=True)]
Password = Annotated[str, StringConstraints(min_length=10, max_length=128)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Password
    full_name: Name


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class ChangePasswordRequest(BaseModel):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    new_password: Password


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    full_name: str
    phone: str | None
    nationality: str | None
    home_airport: str | None


class ProfileUpdate(BaseModel):
    full_name: Name | None = None
    phone: Annotated[str, StringConstraints(pattern=r"^\+?[0-9 ()\-]{6,20}$")] | None = None
    nationality: Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{2}$", to_upper=True,
                                                  strip_whitespace=True)] | None = None
    home_airport: IataAirport | None = None


class FrequentFlyerIn(BaseModel):
    airline: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]
    # Omit to keep the number already stored for this airline (clients only ever see it masked).
    number: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=32)
    ] | None = None


class FrequentFlyerOut(BaseModel):
    airline: str
    number_masked: str


class PreferencesUpdate(BaseModel):
    preferred_airports: list[IataAirport] = Field(default_factory=list, max_length=10)
    preferred_airlines: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]
    ] = Field(default_factory=list, max_length=10)
    preferred_cabin: CabinClass | None = None
    seat_preference: Literal["window", "aisle", "no_preference"] | None = None
    meal_preference: Annotated[str, StringConstraints(max_length=64)] | None = None
    frequent_flyer_programs: list[FrequentFlyerIn] = Field(default_factory=list, max_length=10)
    notes: Annotated[str, StringConstraints(max_length=1000)] | None = None


class PreferencesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    preferred_airports: list[str]
    preferred_airlines: list[str]
    preferred_cabin: CabinClass | None
    seat_preference: str | None
    meal_preference: str | None
    frequent_flyer_programs: list[FrequentFlyerOut]
    notes: str | None

    @field_validator("frequent_flyer_programs", mode="before")
    @classmethod
    def _mask_numbers(cls, value):
        return [
            {"airline": p.get("airline", ""), "number_masked": mask(p.get("number", "")) or ""}
            for p in value or []
        ]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    role: Role
    created_at: UtcDatetime
    profile: ProfileOut
    preferences: PreferencesOut


class AuthResponse(BaseModel):
    user: UserOut
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_at: UtcDatetime
    csrf_token: str
