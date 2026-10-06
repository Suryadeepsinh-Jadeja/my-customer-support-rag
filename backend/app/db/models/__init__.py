"""All ORM models, imported here so Alembic and `Base.metadata` see every table."""

from app.db.models.audit import AuditLog
from app.db.models.user import CabinClass, Role, TravelPreference, User, UserProfile

__all__ = ["AuditLog", "CabinClass", "Role", "TravelPreference", "User", "UserProfile"]
