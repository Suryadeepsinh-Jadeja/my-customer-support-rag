import pytest
from sqlalchemy import select

from app.api.deps import require_admin
from app.core.errors import PermissionDeniedError
from app.db.models import Role, TravelPreference, User
from tests.conftest import bearer


async def test_update_profile(client, user_token):
    response = await client.patch(
        "/api/users/me/profile", headers=bearer(user_token),
        json={"phone": "+41 44 123 45 67", "nationality": "ch", "home_airport": "zrh"},
    )
    assert response.status_code == 200
    profile = response.json()["profile"]
    assert profile == {"full_name": "Ana Traveller", "phone": "+41 44 123 45 67",
                       "nationality": "CH", "home_airport": "ZRH"}


async def test_profile_validation(client, user_token):
    response = await client.patch("/api/users/me/profile", headers=bearer(user_token),
                                  json={"home_airport": "ZURICH"})
    assert response.status_code == 422
    assert response.json()["error"]["fields"][0]["field"] == "home_airport"


async def test_preferences_mask_frequent_flyer_numbers(client, user_token, db_session):
    response = await client.put(
        "/api/users/me/preferences", headers=bearer(user_token),
        json={
            "preferred_airports": ["bom", "ZRH"],
            "preferred_airlines": ["Lufthansa"],
            "preferred_cabin": "economy",
            "seat_preference": "aisle",
            "frequent_flyer_programs": [{"airline": "Miles & More", "number": "992233445566"}],
        },
    )
    assert response.status_code == 200
    prefs = response.json()["preferences"]
    assert prefs["preferred_airports"] == ["BOM", "ZRH"]
    assert prefs["preferred_cabin"] == "economy"
    assert prefs["frequent_flyer_programs"] == [
        {"airline": "Miles & More", "number_masked": "****5566"}
    ]
    assert "992233445566" not in response.text

    stored = (await db_session.execute(select(TravelPreference))).scalar_one()
    assert stored.frequent_flyer_programs[0]["number"] == "992233445566"


async def test_preferences_keep_existing_number_when_omitted(client, user_token, db_session):
    programs = [{"airline": "Miles & More", "number": "992233445566"}]
    await client.put("/api/users/me/preferences", headers=bearer(user_token),
                     json={"frequent_flyer_programs": programs})
    # The UI only knows the masked number, so it resends the program without one.
    response = await client.put("/api/users/me/preferences", headers=bearer(user_token),
                                json={"preferred_cabin": "business",
                                      "frequent_flyer_programs": [{"airline": "Miles & More"}]})
    assert response.status_code == 200
    stored = (await db_session.execute(select(TravelPreference))).scalar_one()
    await db_session.refresh(stored)
    assert stored.frequent_flyer_programs == programs

    unknown = await client.put("/api/users/me/preferences", headers=bearer(user_token),
                               json={"frequent_flyer_programs": [{"airline": "Flying Blue"}]})
    assert unknown.status_code == 422


async def test_require_admin(client, user_token, db_session):
    user = (await db_session.execute(select(User))).scalar_one()
    with pytest.raises(PermissionDeniedError):
        await require_admin(user)
    user.role = Role.ADMIN
    assert await require_admin(user) is user
