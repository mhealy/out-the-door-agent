from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.candidates import router as candidates_router
from app.api.quotes import router as quotes_router
from app.api.outreach import router as outreach_router
from app.api.agent_runs import router as agent_runs_router
from app.api.offer_comparisons import router as offer_comparisons_router
from app.api.purchase_runs import router as purchase_runs_router
from app.config import get_settings
from app.persistence.db import create_schema


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_schema()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.app_name, lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health_router)
    application.include_router(candidates_router)
    application.include_router(quotes_router)
    application.include_router(outreach_router)
    application.include_router(agent_runs_router)
    application.include_router(offer_comparisons_router)
    application.include_router(purchase_runs_router)
    return application


app = create_app()
