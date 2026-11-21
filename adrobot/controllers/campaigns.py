import logging
from collections.abc import Sequence
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from adrobot.controllers.form_requests import read_form, require_same_origin
from adrobot.db import DatabaseSession
from adrobot.diagnostics import request_id
from adrobot.forms.campaign import CampaignForm
from adrobot.keitaro import KeitaroDependency, KeitaroError
from adrobot.keitaro.campaigns import (
    CampaignSummary,
    archive_campaign,
    disable_campaign,
    enable_campaign,
    get_campaign,
    list_campaigns,
)
from adrobot.keitaro.streams import (
    CampaignStream,
    fetch_streams_with_offer_names,
    is_offer_stream,
)
from adrobot.models.offer_draft import (
    CampaignOfferDraft,
    DraftStream,
)
from adrobot.templates import render

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Campaigns"], dependencies=[Depends(require_same_origin)])
SYNC_FLASH_COOKIE = "adrobot_offer_sync"


@router.get("/campaigns/new", name="new_campaign", include_in_schema=False)
def new() -> HTMLResponse:
    return render("campaigns/new.html", "Создание кампании")


def _render_form_error(message: str, status_code: int) -> HTMLResponse:
    return render(
        "campaigns/error.html",
        "Создание кампании",
        message=message,
        status_code=status_code,
    )


@router.post("/campaigns", name="post_campaign", include_in_schema=False)
async def create(request: Request, keitaro: KeitaroDependency) -> Response:
    try:
        form = CampaignForm.model_validate(
            await read_form(request, max_fields=3, keep_blank_values=True)
        )
    except HTTPException as exc:
        return _render_form_error(exc.detail, exc.status_code)
    except ValueError:
        return _render_form_error("Проверьте название, код страны и оффер.", 422)

    try:
        await run_in_threadpool(form.submit, keitaro, request.app.state.settings)
    except KeitaroError as exc:
        return _render_form_error(str(exc), 502)
    return RedirectResponse("/campaigns", status_code=303)


@router.get("/campaigns", name="campaigns_index", include_in_schema=False)
def index(keitaro: KeitaroDependency) -> HTMLResponse:
    try:
        campaigns = list_campaigns(keitaro)
    except KeitaroError as exc:
        return render(
            "campaigns/index.html",
            "Кампании",
            campaigns=[],
            message=str(exc),
            status_code=502,
        )
    return render(
        "campaigns/index.html",
        "Кампании",
        campaigns=campaigns,
        message="" if campaigns else "Кампаний пока нет.",
    )


def render_campaign_detail(
    title: str,
    streams: Sequence[CampaignStream],
    offer_names: dict[int, str],
    *,
    campaign: CampaignSummary | None = None,
    draft_enabled: bool = False,
    sync_pending: bool = False,
    show_sync_notice: bool = False,
    message: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    offer_stream_ids = {stream.id for stream in streams if is_offer_stream(stream)}
    eligible_streams = [
        stream
        for stream in streams
        if stream.id in offer_stream_ids
        and (not isinstance(stream, DraftStream) or stream.available)
    ]
    visible_streams = [stream for stream in streams if stream.offers]
    return render(
        "campaigns/show.html",
        title,
        campaign=campaign,
        editable=campaign is not None and campaign.state in {"active", "disabled"},
        show_form=status_code == 200,
        draft_enabled=draft_enabled,
        sync_pending=sync_pending,
        show_sync_notice=show_sync_notice,
        streams=visible_streams,
        offer_names=offer_names,
        offer_stream_ids=offer_stream_ids,
        eligible_streams=eligible_streams,
        add_enabled=draft_enabled and bool(eligible_streams),
        message=message
        or ("В потоках пока нет офферов." if not visible_streams else ""),
        status_code=status_code,
    )


@router.get(
    "/campaigns/{campaign_id:int}", name="show_campaign", include_in_schema=False
)
def show(
    request: Request,
    campaign_id: Annotated[int, Path(gt=0)],
    keitaro: KeitaroDependency,
    db: DatabaseSession,
) -> HTMLResponse:
    show_sync_notice = request.cookies.get(SYNC_FLASH_COOKIE) == str(campaign_id)
    response = _campaign_page(campaign_id, keitaro, db, show_sync_notice)
    response.headers["Cache-Control"] = "private, no-store"
    if show_sync_notice:
        response.delete_cookie(SYNC_FLASH_COOKIE, path=request.url.path)
    return response


def _campaign_page(
    campaign_id: int,
    keitaro: KeitaroDependency,
    db: DatabaseSession,
    show_sync_notice: bool,
) -> HTMLResponse:
    title = f"Кампания #{campaign_id}"
    try:
        campaign = get_campaign(keitaro, campaign_id)
    except KeitaroError as exc:
        if exc.status_code == 404:
            return render_campaign_detail(
                title, [], {}, message="Кампания не найдена.", status_code=404
            )
        return render_campaign_detail(title, [], {}, message=str(exc), status_code=502)

    draft_enabled = True
    try:
        snapshot = CampaignOfferDraft.load_snapshot(db, campaign_id)
        if snapshot is not None:
            return render_campaign_detail(
                campaign.name,
                snapshot.streams,
                {},
                campaign=campaign,
                draft_enabled=True,
                sync_pending=snapshot.has_pending_changes,
                show_sync_notice=show_sync_notice,
            )
    except (SQLAlchemyError, ValidationError) as exc:
        logger.warning(
            "Draft unavailable request_id=%s campaign=%d error=%s",
            request_id.get(),
            campaign_id,
            type(exc).__name__,
        )
        db.rollback()
        draft_enabled = False

    try:
        streams, offer_names = fetch_streams_with_offer_names(keitaro, campaign_id)
    except KeitaroError as exc:
        return render_campaign_detail(
            campaign.name,
            [],
            {},
            campaign=campaign,
            draft_enabled=draft_enabled,
            message=str(exc),
            status_code=502,
        )

    message = (
        "Не удалось загрузить названия офферов. Показаны их ID."
        if offer_names is None
        else ""
    )
    if not draft_enabled:
        message = f"Черновик недоступен. Показаны офферы из Keitaro. Попробуйте обновить страницу позже. {message}".strip()
    return render_campaign_detail(
        campaign.name,
        streams,
        offer_names or {},
        campaign=campaign,
        show_sync_notice=show_sync_notice,
        draft_enabled=draft_enabled,
        message=message,
    )


@router.post(
    "/campaigns/{campaign_id:int}/state/{action}",
    name="change_campaign_state",
    include_in_schema=False,
)
def change_state(
    campaign_id: Annotated[int, Path(gt=0)],
    action: Literal["enable", "disable"],
    keitaro: KeitaroDependency,
) -> Response:
    set_tracker_state = enable_campaign if action == "enable" else disable_campaign
    try:
        set_tracker_state(keitaro, campaign_id)
    except KeitaroError as exc:
        return render_campaign_detail(
            f"Кампания #{campaign_id}",
            [],
            {},
            message=f"Не удалось изменить статус кампании. {exc}",
            status_code=404 if exc.status_code == 404 else 502,
        )
    return RedirectResponse(f"/campaigns/{campaign_id}", status_code=303)


@router.get(
    "/campaigns/{campaign_id:int}/archive",
    name="confirm_archive_campaign",
    include_in_schema=False,
)
def show_archive_confirmation(
    campaign_id: Annotated[int, Path(gt=0)], keitaro: KeitaroDependency
) -> HTMLResponse:
    try:
        campaign = get_campaign(keitaro, campaign_id)
    except KeitaroError as exc:
        return render_campaign_detail(
            f"Кампания #{campaign_id}",
            [],
            {},
            message=str(exc),
            status_code=404 if exc.status_code == 404 else 502,
        )
    if campaign.state == "deleted":
        return render_campaign_detail(
            campaign.name, [], {}, message="Кампания уже в архиве.", status_code=409
        )
    return render("campaigns/archive.html", "Удаление кампании", campaign=campaign)


@router.post(
    "/campaigns/{campaign_id:int}/archive",
    name="post_archive_campaign",
    include_in_schema=False,
)
def archive(
    campaign_id: Annotated[int, Path(gt=0)],
    keitaro: KeitaroDependency,
) -> Response:
    try:
        archive_campaign(keitaro, campaign_id)
    except KeitaroError as exc:
        return render_campaign_detail(
            f"Кампания #{campaign_id}",
            [],
            {},
            message=f"Не удалось отправить кампанию в архив. {exc}",
            status_code=404 if exc.status_code == 404 else 502,
        )
    return RedirectResponse("/campaigns", status_code=303)
