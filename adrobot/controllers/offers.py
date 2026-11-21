import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from adrobot.controllers.campaigns import SYNC_FLASH_COOKIE, render_campaign_detail
from adrobot.controllers.form_requests import read_form, require_same_origin
from adrobot.db import DatabaseSession
from adrobot.diagnostics import request_id
from adrobot.forms.offer import OfferForm
from adrobot.keitaro import KeitaroDependency, KeitaroError
from adrobot.keitaro.offers import OfferSummary, search_offers
from adrobot.models.offer_draft import DraftError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Offers"])


@router.get("/api/offers/search", name="get_offer_matches")
def search(
    q: Annotated[str, Query(min_length=1, max_length=200)],
    keitaro: KeitaroDependency,
) -> list[OfferSummary]:
    try:
        return search_offers(keitaro, q)
    except KeitaroError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post(
    "/campaigns/{campaign_id:int}/draft",
    name="post_campaign_draft",
    include_in_schema=False,
    dependencies=[Depends(require_same_origin)],
)
async def update_draft(
    request: Request,
    campaign_id: Annotated[int, Path(gt=0)],
    keitaro: KeitaroDependency,
    db: DatabaseSession,
) -> Response:
    try:
        form = OfferForm.model_validate(await read_form(request, max_fields=3))
    except ValidationError as exc:
        error = exc.errors()[0]
        message = (
            error["msg"]
            if error["type"] == "missing_offer_target"
            else "Некорректные данные черновика."
        )
        raise HTTPException(422, message) from exc
    except ValueError as exc:
        raise HTTPException(422, "Некорректные данные черновика.") from exc

    try:
        await run_in_threadpool(form.submit, db, keitaro, campaign_id)
    except (DraftError, KeitaroError, SQLAlchemyError, ValidationError) as exc:
        logger.warning(
            "Draft update failed request_id=%s campaign=%d action=%s error=%s",
            request_id.get(),
            campaign_id,
            form.action,
            type(exc).__name__,
        )
        if isinstance(exc, DraftError):
            message, status = str(exc), 409
        elif isinstance(exc, KeitaroError):
            message, status = str(exc), 404 if exc.status_code == 404 else 502
        else:
            message, status = "Не удалось сохранить черновик в базе данных.", 503
        return render_campaign_detail(
            f"Кампания #{campaign_id}", [], {}, message=message, status_code=status
        )
    path = request.url_for("show_campaign", campaign_id=campaign_id).path
    response = RedirectResponse(path, status_code=303)
    if form.action == "sync":
        response.set_cookie(
            SYNC_FLASH_COOKIE,
            str(campaign_id),
            path=path,
            max_age=60,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
        )
    return response
