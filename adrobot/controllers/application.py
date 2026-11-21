from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from adrobot import STATIC_DIR
from adrobot.db import DatabaseSession

router = APIRouter()


class Health(BaseModel):
    status: str


@router.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@router.get("/api/health", responses={503: {"description": "Database unavailable"}})
def health(session: DatabaseSession) -> Health:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Database unavailable") from exc
    return Health(status="ok")
