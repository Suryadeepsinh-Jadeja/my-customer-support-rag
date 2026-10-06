"""Booking providers. Only the mock exists until phase 7 adds a real flight provider
(chosen with a FLIGHT_PROVIDER setting)."""

from app.providers.base import BookingProvider, ProviderError
from app.providers.mock import MockProvider

__all__ = ["BookingProvider", "ProviderError", "get_provider"]


def get_provider(kind: str) -> BookingProvider:
    return MockProvider(kind)
