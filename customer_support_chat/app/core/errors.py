"""Application errors and the customer-facing messages they map to.

Internal details are logged; customers only ever see the `user_message`.
"""


class SupportError(Exception):
    status_code = 500
    code = "internal_error"
    user_message = "Something went wrong on our side. Please try again in a moment."


class CustomerNotIdentifiedError(SupportError, ValueError):
    status_code = 401
    code = "not_authenticated"
    user_message = (
        "We couldn't identify your customer account. "
        "Please sign in again with your passenger ID and booking reference."
    )

    def __init__(self, message: str = "No passenger ID configured."):
        super().__init__(message)


class ConfigurationError(SupportError):
    status_code = 503
    code = "service_unavailable"
    user_message = (
        "The support assistant is not available right now because it is not fully configured. "
        "Please try again later."
    )


class AssistantUnavailableError(SupportError):
    status_code = 503
    code = "assistant_unavailable"
    user_message = (
        "Our assistant is temporarily unavailable. Please try again in a moment."
    )


class AssistantBusyError(SupportError):
    status_code = 429
    code = "rate_limited"
    user_message = (
        "We're handling a lot of requests right now. Please wait a minute and try again."
    )


class AssistantTimeoutError(SupportError):
    status_code = 504
    code = "timeout"
    user_message = (
        "This is taking longer than expected. Please try again; if you asked for a change, "
        "check your bookings before repeating it."
    )


class ConversationNotFoundError(SupportError):
    status_code = 404
    code = "conversation_not_found"
    user_message = "This conversation has expired. Please start a new conversation."


class NoPendingActionError(SupportError):
    status_code = 409
    code = "no_pending_action"
    user_message = "There is no pending action waiting for your confirmation."


class ConversationBusyError(SupportError):
    status_code = 409
    code = "conversation_busy"
    user_message = "Please wait for the current reply before sending another message."
