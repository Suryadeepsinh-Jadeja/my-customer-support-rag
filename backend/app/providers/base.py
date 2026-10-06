"""What a booking provider must offer. Offers and results are plain JSON-ready dicts."""

from typing import Any


class ProviderError(Exception):
    """The provider refused or failed. `code` is safe to show and to store."""

    def __init__(self, code: str, message: str = "The provider couldn't complete that."):
        super().__init__(code)
        self.code = code
        self.message = message


class BookingProvider:
    name = "base"

    async def search(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def get_offer(self, offer_id: str) -> dict[str, Any]:
        """The offer as currently priced. Raises ProviderError("offer_not_found")."""
        raise NotImplementedError

    async def book(self, offer: dict[str, Any], travellers: list[str]) -> str:
        """Book the offer; returns the provider's confirmation reference."""
        raise NotImplementedError

    async def refund_quote(self, details: dict[str, Any], amount: float) -> dict[str, Any]:
        """{"refund_amount", "fee", "currency"} if the booking were cancelled now."""
        raise NotImplementedError

    async def cancel(self, provider_ref: str, details: dict[str, Any],
                     amount: float) -> dict[str, Any]:
        """Cancel; returns the refund actually granted (same shape as refund_quote)."""
        raise NotImplementedError

    async def modify_quote(self, details: dict[str, Any],
                           changes: dict[str, str]) -> dict[str, Any]:
        """The offer the booking would become with new dates (no side effects)."""
        raise NotImplementedError

    async def modify(self, provider_ref: str, details: dict[str, Any],
                     changes: dict[str, str]) -> dict[str, Any]:
        """Change the booking's dates; returns the new offer."""
        raise NotImplementedError
