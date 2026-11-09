import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request

from app.core.logging import setup_logging
from app.db.database import check_database

setup_logging()

logger = logging.getLogger("fleetlink")

app = FastAPI(
    title="InGen FleetLink",
    description="Fleet connectivity and mission backend",
    version="0.1.0",
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = str(uuid.uuid4())
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
        raise

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
