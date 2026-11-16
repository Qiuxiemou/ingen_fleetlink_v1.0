import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.api.robots import ErrorDetail, ErrorResponse
from app.api.robots import router as robots_router
from app.core.logging import setup_logging
from app.db.database import check_database
from app.gateway.link import router as link_router

setup_logging()

logger = logging.getLogger("fleetlink")

app = FastAPI(
    title="InGen FleetLink",
    description="Fleet connectivity and mission backend",
    version="0.1.0",
)
app.include_router(robots_router)
app.include_router(link_router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    start_time = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "HTTP request failed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": 500,
            },
        )
        if not request.url.path.startswith("/v1/"):
            raise
        response = versioned_error(
            request, 500, "INTERNAL_ERROR", "Internal server error"
        )

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

    response.headers["X-Request-ID"] = request_id

    logger.info(
        "HTTP request completed in %s ms",
        duration_ms,
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
        },
    )

    return response


def versioned_error(
    request: Request, status: int, code: str, message: str
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message),
        request_id=request.state.request_id,
    )
    return JSONResponse(status_code=status, content=body.model_dump())


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(request: Request, exc: StarletteHTTPException) -> Response:
    if not request.url.path.startswith("/v1/"):
        return await http_exception_handler(request, exc)
    if isinstance(exc.detail, dict):
        code, message = exc.detail["code"], exc.detail["message"]
    else:
        code, message = f"HTTP_{exc.status_code}", str(exc.detail)
    response = versioned_error(request, exc.status_code, code, message)
    if exc.headers:
        response.headers.update(exc.headers)
    return response


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request, exc: RequestValidationError
) -> Response:
    if not request.url.path.startswith("/v1/"):
        return await request_validation_exception_handler(request, exc)
    return versioned_error(request, 422, "VALIDATION_ERROR", "Invalid request data")


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Welcome to InGen FleetLink"}


@app.get("/healthz")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readiness_check() -> dict[str, str]:
    if not check_database():
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        )

    return {"status": "ready"}
