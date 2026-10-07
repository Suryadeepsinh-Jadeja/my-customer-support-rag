"""Typed application errors and the handlers that turn them into safe JSON responses.

Every error response has the shape {"error": {"code": ..., "message": ...}} and never
contains a stack trace or internal detail.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("travel.errors")


class AppError(Exception):
    status_code = 500
    code = "internal_error"
    message = "Something went wrong on our side. Please try again."

    def __init__(self, message: str | None = None, *, headers: dict[str, str] | None = None):
        super().__init__(message or self.message)
        if message:
            self.message = message
        self.headers = headers


class InvalidRequestError(AppError):
    status_code = 422
    code = "invalid_request"
    message = "Some of the information provided is invalid."


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "file_too_large"
    message = "That file is too large."


class UnsupportedFileError(AppError):
    status_code = 415
    code = "unsupported_file"
    message = "That file type isn't supported. Upload a PDF, Word document, text file, PNG or JPEG."


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "The service is temporarily unavailable. Please try again shortly."


class InvalidCredentialsError(AppError):
    status_code = 401
    code = "invalid_credentials"
    message = "The email or password is incorrect."


class NotAuthenticatedError(AppError):
    status_code = 401
    code = "not_authenticated"
    message = "Please sign in to continue."


class CsrfError(AppError):
    status_code = 403
    code = "csrf_failed"
    message = "Your session could not be verified. Please reload the page."


class PermissionDeniedError(AppError):
    status_code = 403
    code = "forbidden"
    message = "You don't have permission to do that."


class AccountLockedError(AppError):
    status_code = 429
    code = "too_many_attempts"
    message = "Too many unsuccessful sign-in attempts. Please wait a few minutes and try again."


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests. Please slow down and try again shortly."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "That conflicts with existing data."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "We couldn't find that."


def _error(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message, **extra}}
    )


_HTTP_CODES = {
    400: "bad_request",
    401: "not_authenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    415: "unsupported_media_type",
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        response = _error(exc.status_code, exc.code, exc.message)
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        # Report where the problem is, but never echo submitted values (they may be passwords).
        fields = [
            {"field": ".".join(str(p) for p in err["loc"] if p != "body"), "issue": err["msg"]}
            for err in exc.errors()
        ]
        return _error(422, "invalid_request", "Some of the information provided is invalid.",
                      fields=fields)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return _error(exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logger.exception("Unhandled error")
        return _error(500, AppError.code, AppError.message)
