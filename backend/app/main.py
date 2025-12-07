"""
OneSearch FastAPI Application
Main entry point for the backend API
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .services.search import meili_service

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
    logger.info(f"Database: {settings.database_url}")
    logger.info(f"Meilisearch: {settings.meili_url}")

    # Initialize Meilisearch connection
    if meili_service.connect():
        logger.info("Meilisearch connection established")
    else:
        logger.warning("Failed to connect to Meilisearch - some features may not work")

    yield

    # Shutdown
    logger.info("Shutting down OneSearch API...")


# Create FastAPI app
app = FastAPI(
    title="OneSearch API",
    description="Self-hosted, privacy-focused search for your homelab",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:8000",  # Production (nginx)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health_check():
    """
    Health check endpoint for container healthcheck

    Returns service status and basic configuration info
    """
    # Check Meilisearch health
    meili_health = meili_service.health_check()

    # Overall status is healthy if Meilisearch is connected
    overall_status = "healthy" if meili_health.get("status") in ["available", "unknown"] else "degraded"

    return {
        "status": overall_status,
        "service": "onesearch-backend",
        "version": "0.1.0",
        "meilisearch": meili_health,
        "config": {
            "database": settings.database_url.split("///")[0],  # Just the protocol
            "meilisearch_url": settings.meili_url,
            "log_level": settings.log_level,
        },
    }


@app.get("/")
async def root():
    """Root endpoint - API information"""
    return {
        "message": "OneSearch API",
        "version": "0.1.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/api/health",
    }
