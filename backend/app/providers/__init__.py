"""Booking providers: the mock for everything, or Duffel for flights (FLIGHT_PROVIDER)."""

from app.core.config import get_settings
from app.providers.base import BookingProvider, ProviderError
from app.providers.duffel import DuffelProvider
from app.providers.mock import MockProvider

__all__ = ["BookingProvider", "ProviderError", "get_provider"]


def get_provider(kind: str) -> BookingProvider:
    settings = get_settings()
    if kind == "flight" and settings.FLIGHT_PROVIDER == "duffel":
        if not settings.DUFFEL_API_KEY:
            raise ProviderError("provider_not_configured", "Flight booking isn't available.")
        return DuffelProvider(settings.DUFFEL_API_KEY, settings.DUFFEL_BASE_URL)
    return MockProvider(kind)
