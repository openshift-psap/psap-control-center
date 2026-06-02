from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import asyncio

from app.core.config import settings
from app.core.database import init_db, engine, AsyncSessionLocal
from app.api import api_router
from app.utils.logger import create_logger, set_log_level_from_env

set_log_level_from_env()
logger = create_logger("Main")


async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler to prevent raw exception details from leaking to clients."""
    logger.error("Unhandled exception:", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Please try again later."}
    )


async def update_reservation_statuses_task():
    """Background task to periodically update reservation statuses and reconcile enforcement."""
    from app.services.reservation_service import ReservationService
    from app.services.enforcement_service import ReservationEnforcementService

    while True:
        try:
            async with AsyncSessionLocal() as session:
                service = ReservationService(session)
                await service.update_reservation_statuses()

                enforcement = ReservationEnforcementService(session)
                result = enforcement.reconcile()
                if asyncio.iscoroutine(result):
                    result = await result
                if result.get("provisioned") or result.get("cleaned"):
                    logger.info(f"Enforcement reconcile: {result}")
        except Exception as e:
            logger.error(f"Error in reservation background task: {e}")

        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up PSAP Control Center...")
    await init_db()
    logger.info("Database initialized")
    
    # Start background task for reservation status updates
    status_task = asyncio.create_task(update_reservation_statuses_task())
    logger.info("Reservation status updater started")
    
    yield
    
    # Cleanup
    status_task.cancel()
    try:
        await status_task
    except asyncio.CancelledError:
        pass
    
    await engine.dispose()
    logger.info("Shutting down PSAP Control Center...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Performance and Scale for AI Platforms - Cluster Management & Reservation System",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)
app.add_exception_handler(Exception, global_exception_handler)


@app.get("/")
async def root():
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs": "/docs",
        "api": settings.API_V1_PREFIX
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
