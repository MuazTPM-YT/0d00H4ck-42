import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException

log = logging.getLogger(__name__)


class AppError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str, field: str | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field
        if code:
            self.code = code


class BadRequest(AppError):
    status, code = 400, "bad_request"


class Unauthorized(AppError):
    status, code = 401, "unauthorized"


class Forbidden(AppError):
    status, code = 403, "forbidden"


class NotFound(AppError):
    status, code = 404, "not_found"


class Conflict(AppError):
    status, code = 409, "conflict"


class Unprocessable(AppError):
    status, code = 422, "validation_error"


# raise inside a pydantic validator to point the error at one field
class FieldError(ValueError):
    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


def error_body(code: str, message: str, field: str | None = None) -> dict:
    return {"error": {"code": code, "message": message, "field": field}}


def _json(status: int, code: str, message: str, field: str | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=error_body(code, message, field))


HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
}


# every failure leaves the API in one shape: {"error": {code, message, field}}
def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(_: Request, e: AppError):
        return _json(e.status, e.code, e.message, e.field)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, e: RequestValidationError):
        first = e.errors()[0]
        loc = [str(p) for p in first["loc"] if p not in ("body", "query", "path")]
        msg = first["msg"].removeprefix("Value error, ")
        field = getattr(first.get("ctx", {}).get("error"), "field", None) or ".".join(loc)
        return _json(422, "validation_error", msg, field or None)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, e: HTTPException):
        return _json(e.status_code, HTTP_CODES.get(e.status_code, "error"), str(e.detail))

    # DB is last guard: unique -> 409, check/fk/not-null -> 422
    @app.exception_handler(IntegrityError)
    async def integrity_error(_: Request, e: IntegrityError):
        diag = getattr(e.orig, "diag", None)
        constraint = getattr(diag, "constraint_name", None)
        if getattr(e.orig, "sqlstate", None) == "23505":
            field = (constraint or "").removeprefix(f"uq_{getattr(diag, 'table_name', '')}_")
            return _json(409, "duplicate", "A record with this value already exists", field or None)
        return _json(
            422, "constraint_violation", f"Rejected by database rule ({constraint})", constraint
        )

    @app.exception_handler(NotImplementedError)
    async def not_implemented(_: Request, e: NotImplementedError):
        return _json(501, "not_implemented", str(e) or "This feature is being built")

    @app.exception_handler(Exception)
    async def unexpected(_: Request, e: Exception):
        log.exception("unhandled error")
        return _json(500, "internal_error", "Something went wrong on the server")
