from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import RequestResponseEndpoint

from adrobot import STATIC_DIR
from adrobot.controllers.application import router as application_router
from adrobot.controllers.campaigns import router as campaigns_router
from adrobot.controllers.offers import router as offers_router
from adrobot.db import create_database_engine
from adrobot.diagnostics import request_id
from adrobot.keitaro import KeitaroConfigurationError, open_keitaro_client
from adrobot.settings import Settings


def create_app(database_url: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = Settings(database_url=database_url) if database_url else Settings()
        app.state.settings = settings
        with ExitStack() as stack:
            engine = create_database_engine(settings.database_url)
            stack.callback(engine.dispose)
            app.state.engine = engine
            try:
                app.state.keitaro_client = stack.enter_context(
                    open_keitaro_client(settings)
                )
            except KeitaroConfigurationError:
                app.state.keitaro_client = None
            yield

    app = FastAPI(title="Adrobot", lifespan=lifespan)

    @app.middleware("http")
    async def identify_request(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        identifier = uuid4().hex
        token = request_id.set(identifier)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = identifier
            return response
        finally:
            request_id.reset(token)

    app.mount("/static/css", StaticFiles(directory=STATIC_DIR / "css"), name="css")
    app.mount(
        "/static/icons", StaticFiles(directory=STATIC_DIR / "icons"), name="icons"
    )
    app.mount("/static/js", StaticFiles(directory=STATIC_DIR / "js"), name="js")
    app.include_router(campaigns_router)
    app.include_router(offers_router)
    app.include_router(application_router)

    return app


app = create_app()
