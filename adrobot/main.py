import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from adrobot.campaigns import router as campaigns_router

INDEX = Path(__file__).parent / "static" / "index.html"


class Health(BaseModel):
    status: str


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


def create_app(database_url: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(
            database_url or os.environ.get("DATABASE_URL", "sqlite:///adrobot.db"),
            pool_pre_ping=True,
        )
        app.state.engine = engine
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="Adrobot", lifespan=lifespan)
    app.include_router(campaigns_router)

    @app.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(INDEX, media_type="text/html")

    @app.get("/api/health", responses={503: {"description": "Database unavailable"}})
    def health(session: Annotated[Session, Depends(get_session)]) -> Health:
        try:
            session.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise HTTPException(503, "Database unavailable") from exc
        return Health(status="ok")

    return app


app = create_app()
