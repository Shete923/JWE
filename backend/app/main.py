import logging
import os

import psycopg
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.retail import router as retail_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Jewellery Management API",
    version="0.2.0",
    description="Local retail, inventory, and jewellery sales API.",
)
app.include_router(retail_router)


@app.exception_handler(psycopg.IntegrityError)
async def handle_integrity_error(
    _request: Request, exc: psycopg.IntegrityError
) -> JSONResponse:
    logger.warning("Database rejected a conflicting retail operation: %s", exc.sqlstate)
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": (
                "The change conflicts with existing data. Check for a duplicate "
                "email, item prefix, tag number, or related record."
            )
        },
    )


@app.exception_handler(psycopg.Error)
async def handle_database_error(_request: Request, exc: psycopg.Error) -> JSONResponse:
    logger.exception("Unexpected database error in retail API: %s", exc.sqlstate)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Database operation failed; see the backend log for details."},
    )


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/db", tags=["health"])
def database_health_check() -> dict[str, str]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise HTTPException(
            status_code=503,
            detail="DATABASE_URL is not configured.",
        )

    try:
        with psycopg.connect(database_url, connect_timeout=3) as connection:
            result = connection.execute(
                """
                SELECT to_regclass('jewellery.shop_settings'),
                       to_regclass('jewellery.savings_scheme'),
                       to_regclass('jewellery.scheme_installment')
                """
            ).fetchone()
    except psycopg.Error as exc:
        logger.exception("PostgreSQL health check failed")
        raise HTTPException(
            status_code=503,
            detail="PostgreSQL is unavailable; see the application log for details.",
        ) from exc

    if not result or result[0] is None:
        raise HTTPException(
            status_code=503,
            detail="Retail schema migration 002 is not applied.",
        )
    if result[1] is None or result[2] is None:
        raise HTTPException(
            status_code=503,
            detail="Ledger and scheme migration 003 is not applied.",
        )
    return {"status": "ok", "database": "ok", "schema": "ok"}
