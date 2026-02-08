# Copyright (C) 2025 demigodmode
# SPDX-License-Identifier: AGPL-3.0-only

"""
OneSearch FastAPI Application
Main entry point for the backend API
"""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import __version__
from .db.database import get_db
from .config import settings
from .services.search import meili_service
from .services.scheduler import SchedulerService
from .db.database import engine
from .api import sources, search, status, auth

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info("Starting OneSearch API...")
    logger.info(f"Log level: {settings.log_level}")
    logger.info(f"Database: {settings.database_url.split('://')[0]}")
    logger.info(f"Meilisearch: {settings.meili_url}")

    # Initialize Meilisearch connection
    if meili_service.connect():
        logger.info("Meilisearch connection established")
    else:
        logger.warning("Failed to connect to Meilisearch - some features may not work")

    # Start scheduler
    scheduler = SchedulerService(engine)
    scheduler.start()
    app.state.scheduler = scheduler

    yield

    # Shutdown
    scheduler.shutdown()
    logger.info("Shutting down OneSearch API...")


# Create FastAPI app
app = FastAPI(
    title="OneSearch API",
    description="Self-hosted, privacy-focused search for your homelab",
    version=__version__,
    lifespan=lifespan,
)

# Configure CORS
cors_origins = (
    [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if settings.cors_origins
    else ["http://localhost:5173", "http://localhost:8000"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Log all HTTP requests and responses with timing information
    """
    start_time = time.time()

    # Log incoming request (query params and client only at DEBUG level for privacy)
    logger.info(
        f"→ {request.method} {request.url.path}",
        extra={
            "method": request.method,
            "path": request.url.path,
        }
    )

    # Log query params and client at DEBUG level to avoid PII leakage
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            f"Request details: query={request.query_params}, client={request.client.host if request.client else None}"
        )

    # Process request
    try:
        response = await call_next(request)

        # Calculate processing time
        process_time = time.time() - start_time

        # Log response
        log_level = logging.INFO if response.status_code < 400 else logging.WARNING
        logger.log(
            log_level,
            f"← {request.method} {request.url.path} → {response.status_code} ({process_time*1000:.2f}ms)",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "process_time_ms": round(process_time * 1000, 2),
            }
        )

        # Add processing time header
        response.headers["X-Process-Time"] = str(process_time)

        return response

    except Exception as e:
        process_time = time.time() - start_time
        logger.error(
            f"✗ {request.method} {request.url.path} → ERROR ({process_time*1000:.2f}ms): {e}",
            extra={
                "method": request.method,
                "path": request.url.path,
                "error": str(e),
                "process_time_ms": round(process_time * 1000, 2),
            },
            exc_info=True
        )
        raise


# Include API routers
app.include_router(auth.router)
app.include_router(sources.router)
app.include_router(search.router)
app.include_router(status.router)


@app.get("/api/health")
async def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint for container healthcheck

    Returns minimal status info publicly. Detailed config is omitted
    to avoid leaking infrastructure details to unauthenticated requests.
    """
    from .api.auth import is_setup_required

    # Check Meilisearch health
    meili_health = meili_service.health_check()

    # Check if initial setup is required
    setup_required = is_setup_required(db)

    # Overall status — "unknown" means Meilisearch couldn't be reached
    meili_status = meili_health.get("status")
    if meili_status == "available":
        overall_status = "healthy"
    else:
        overall_status = "degraded"

    response_data = {
        "status": overall_status,
        "service": "onesearch-backend",
        "version": __version__,
        "setup_required": setup_required,
        "meilisearch": {
            "status": meili_health.get("status", "unknown"),
        },
    }

    status_code = 200 if overall_status == "healthy" else 503
    return JSONResponse(content=response_data, status_code=status_code)


@app.get("/")
async def root():
    """Root endpoint - API information"""
    return {
        "message": "OneSearch API",
        "version": __version__,
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/api/health",
    }
