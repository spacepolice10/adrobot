import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Self

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import JSON, BigInteger, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from adrobot.db import Base
from adrobot.diagnostics import request_id
from adrobot.keitaro import KeitaroClient, KeitaroError
from adrobot.keitaro.campaigns import get_campaign
from adrobot.keitaro.offers import search_offers
from adrobot.keitaro.streams import (
    CampaignStream,
    StreamOffer,
    fetch_streams_with_offer_names,
    is_offer_stream,
    list_campaign_streams,
    replace_stream_offers,
)

logger = logging.getLogger(__name__)


class DraftError(ValueError):
    pass


class DraftOffer(StreamOffer):
    name: str = "—"
    pinned: bool = False

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_state(cls, data: object) -> object:
        if (
            isinstance(data, dict)
            and data.get("state") == "active"
            and data.get("published") is False
        ):
            return {**data, "state": "Pending"}
        return data

    @property
    def is_selected_for_publication(self) -> bool:
        return self.state in {"Pending", "active"}


class DraftStream(CampaignStream):
    flow_schema: str | None = None
    offers: list[DraftOffer] = Field(default_factory=list)
    available: bool = True
    edited: bool = False
    published_offers: list[StreamOffer] | None = None

    def get_offer(self, offer_id: int) -> DraftOffer:
        for offer in self.offers:
            if offer.offer_id == offer_id:
                return offer
        raise DraftError("Оффер не найден в черновике.")

    def require_available(self) -> None:
        if not self.available:
            raise DraftError("Поток больше недоступен в Keitaro.")

    def redistribute_shares(self) -> None:
        selected = [offer for offer in self.offers if offer.is_selected_for_publication]
        remaining = 100 - sum(offer.share for offer in selected if offer.pinned)
        if remaining < 0:
            raise DraftError("Закреплённые доли превышают 100%.")
        unpinned = sorted(
            (offer for offer in selected if not offer.pinned),
            key=lambda offer: offer.offer_id,
        )
        if unpinned:
            share, extra = divmod(remaining, len(unpinned))
            for index, offer in enumerate(unpinned):
                offer.share = share + int(index < extra)

    @property
    def removed_offer_ids(self) -> set[int]:
        return {offer.offer_id for offer in self.offers if offer.state == "Removed"}

    def build_replacement(self) -> list[StreamOffer] | None:
        """Return the full list to publish. An empty list clears the stream. None skips the write."""
        desired = [
            StreamOffer(offer_id=offer.offer_id, share=offer.share, state="active")
            for offer in self.offers
            if offer.is_selected_for_publication
        ]
        baseline = self.published_offers
        if baseline is None:
            return desired if self.edited else None
        active_baseline = [offer for offer in baseline if offer.state == "active"]
        removed = self.removed_offer_ids
        if _assignment_signature(desired) != _assignment_signature(
            active_baseline
        ) or any(offer.offer_id in removed for offer in baseline):
            return desired
        return None


class DraftSnapshot(BaseModel):
    streams: list[DraftStream]

    @classmethod
    def from_streams(cls, streams: list[CampaignStream], names: dict[int, str]) -> Self:
        return cls(
            streams=[
                DraftStream(
                    id=stream.id,
                    name=stream.name,
                    flow_schema=stream.flow_schema,
                    published_offers=stream.offers,
                    offers=[
                        DraftOffer(
                            **offer.model_dump(), name=names.get(offer.offer_id, "—")
                        )
                        for offer in stream.offers
                    ],
                )
                for stream in streams
                if is_offer_stream(stream)
            ]
        )

    def reconcile(self, published: Self) -> None:
        remote_streams = {stream.id: stream for stream in published.streams}
        for stream in self.streams:
            remote = remote_streams.pop(stream.id, None)
            stream.available = remote is not None
            if remote is not None:
                stream.name = remote.name
                stream.published_offers = remote.published_offers
            else:
                stream.published_offers = []
            remote_offers = (
                {offer.offer_id: offer for offer in remote.offers} if remote else {}
            )
            previous_selected_ids = {
                offer.offer_id
                for offer in stream.offers
                if offer.is_selected_for_publication
            }
            for offer in stream.offers:
                current = remote_offers.pop(offer.offer_id, None)
                if current is None:
                    if offer.state != "Pending":
                        offer.state = "Removed"
                    continue
                if current.name != "—":
                    offer.name = current.name
                if offer.state == "Removed":
                    continue
                if offer.state == "Pending" and current.state != "active":
                    continue
                offer.state = current.state
                if not stream.edited and not offer.pinned:
                    offer.share = current.share
            stream.offers.extend(remote_offers.values())
            selected_ids = {
                offer.offer_id
                for offer in stream.offers
                if offer.is_selected_for_publication
            }
            if selected_ids != previous_selected_ids:
                stream.redistribute_shares()
        self.streams.extend(remote_streams.values())

    @property
    def has_pending_changes(self) -> bool:
        return any(
            stream.build_replacement() is not None or stream.removed_offer_ids
            for stream in self.streams
        )


class CampaignOfferDraft(Base):
    """A campaign’s local offer assignments and their publication to Keitaro."""

    __tablename__ = "campaign_offer_drafts"

    campaign_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False
    )
    snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)

    @classmethod
    def load_snapshot(cls, db: Session, campaign_id: int) -> DraftSnapshot | None:
        row = db.get(cls, campaign_id)
        return DraftSnapshot.model_validate(row.snapshot) if row is not None else None

    @classmethod
    def add_offer(
        cls,
        db: Session,
        keitaro: KeitaroClient,
        campaign_id: int,
        *,
        stream_id: int,
        offer_id: int,
    ) -> None:
        baseline = cls._prepare_edit(db, keitaro, campaign_id)
        name = _find_offer_name(keitaro, offer_id)
        with cls._edit_stream(db, campaign_id, stream_id, baseline) as stream:
            stream.require_available()
            if any(offer.offer_id == offer_id for offer in stream.offers):
                raise DraftError(
                    "Оффер уже есть в черновике. Используйте восстановление, если он удалён."
                )
            if name is None:
                raise DraftError("Оффер недоступен в Keitaro.")
            stream.offers.append(
                DraftOffer(offer_id=offer_id, name=name, share=0, state="Pending")
            )

    @classmethod
    def remove_offer(
        cls,
        db: Session,
        keitaro: KeitaroClient,
        campaign_id: int,
        *,
        stream_id: int,
        offer_id: int,
    ) -> None:
        baseline = cls._prepare_edit(db, keitaro, campaign_id)
        with cls._edit_stream(db, campaign_id, stream_id, baseline) as stream:
            offer = stream.get_offer(offer_id)
            if (
                offer.state == "Pending"
                and stream.published_offers is not None
                and not any(
                    item.offer_id == offer_id for item in stream.published_offers
                )
            ):
                stream.offers.remove(offer)
            else:
                offer.state = "Removed"

    @classmethod
    def restore_offer(
        cls,
        db: Session,
        keitaro: KeitaroClient,
        campaign_id: int,
        *,
        stream_id: int,
        offer_id: int,
    ) -> None:
        baseline = cls._prepare_edit(db, keitaro, campaign_id)
        name = _find_offer_name(keitaro, offer_id)
        with cls._edit_stream(db, campaign_id, stream_id, baseline) as stream:
            stream.require_available()
            offer = stream.get_offer(offer_id)
            if name is None:
                raise DraftError("Оффер недоступен в Keitaro.")
            if offer.state != "Removed":
                raise DraftError("Восстановить можно только удалённый оффер.")
            already_active = any(
                item.offer_id == offer_id and item.state == "active"
                for item in stream.published_offers or []
            )
            offer.state = "active" if already_active else "Pending"
            offer.name = name

    @classmethod
    def pin_offer(
        cls,
        db: Session,
        keitaro: KeitaroClient,
        campaign_id: int,
        *,
        stream_id: int,
        offer_id: int,
    ) -> None:
        cls._set_offer_pinned(
            db, keitaro, campaign_id, stream_id, offer_id, pinned=True
        )

    @classmethod
    def unpin_offer(
        cls,
        db: Session,
        keitaro: KeitaroClient,
        campaign_id: int,
        *,
        stream_id: int,
        offer_id: int,
    ) -> None:
        cls._set_offer_pinned(
            db, keitaro, campaign_id, stream_id, offer_id, pinned=False
        )

    @classmethod
    def refresh(cls, db: Session, keitaro: KeitaroClient, campaign_id: int) -> None:
        _require_editable_campaign(keitaro, campaign_id)
        published = _fetch_snapshot(keitaro, campaign_id)
        draft = cls._lock_draft(db, campaign_id)
        if draft is None:
            draft = cls(campaign_id=campaign_id)
            snapshot = published
        else:
            snapshot = DraftSnapshot.model_validate(draft.snapshot)
            snapshot.reconcile(published)
        draft._save_snapshot(db, snapshot)

    @classmethod
    def publish(cls, db: Session, keitaro: KeitaroClient, campaign_id: int) -> None:
        _require_editable_campaign(keitaro, campaign_id)
        draft = cls._lock_draft(db, campaign_id)
        if draft is None:
            raise DraftError("Сначала обновите офферы из Keitaro.")
        draft._publish_locked(db, keitaro)

    @classmethod
    def _set_offer_pinned(
        cls,
        db: Session,
        keitaro: KeitaroClient,
        campaign_id: int,
        stream_id: int,
        offer_id: int,
        *,
        pinned: bool,
    ) -> None:
        baseline = cls._prepare_edit(db, keitaro, campaign_id)
        with cls._edit_stream(db, campaign_id, stream_id, baseline) as stream:
            offer = stream.get_offer(offer_id)
            if not offer.is_selected_for_publication:
                raise DraftError("Закреплять можно только активный оффер.")
            offer.pinned = pinned

    @classmethod
    def _prepare_edit(
        cls, db: Session, keitaro: KeitaroClient, campaign_id: int
    ) -> DraftSnapshot | None:
        _require_editable_campaign(keitaro, campaign_id)
        if db.get(cls, campaign_id) is None:
            return _fetch_snapshot(keitaro, campaign_id)
        return None

    @classmethod
    @contextmanager
    def _edit_stream(
        cls,
        db: Session,
        campaign_id: int,
        stream_id: int,
        baseline: DraftSnapshot | None,
    ) -> Iterator[DraftStream]:
        draft = cls._lock_draft(db, campaign_id)
        if draft is None:
            if baseline is None:
                raise DraftError("Сначала обновите черновик из Keitaro.")
            draft = cls(campaign_id=campaign_id)
            snapshot = baseline
        else:
            snapshot = DraftSnapshot.model_validate(draft.snapshot)
        for stream in snapshot.streams:
            if stream.id == stream_id:
                yield stream
                stream.edited = True
                stream.redistribute_shares()
                draft._save_snapshot(db, snapshot)
                return
        raise DraftError("Поток не найден в черновике.")

    def _save_snapshot(self, db: Session, snapshot: DraftSnapshot) -> None:
        self.snapshot = snapshot.model_dump()
        db.add(self)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise DraftError(
                "Черновик уже создан другим запросом. Обновите страницу."
            ) from exc

    @classmethod
    def _lock_draft(cls, db: Session, campaign_id: int) -> Self | None:
        return db.scalar(
            select(cls)
            .where(cls.campaign_id == campaign_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )

    def _publish_locked(self, db: Session, keitaro: KeitaroClient) -> None:
        campaign_id = self.campaign_id
        snapshot = DraftSnapshot.model_validate(self.snapshot)
        pending = []
        cleanup = []
        for stream in snapshot.streams:
            desired = stream.build_replacement()
            if desired is None:
                removed_ids = stream.removed_offer_ids
                if removed_ids:
                    cleanup.append((stream, removed_ids))
                continue
            baseline = stream.published_offers
            if baseline is None:
                raise DraftError(
                    "Сначала обновите офферы из Keitaro и проверьте правки."
                )
            if not stream.available:
                raise DraftError(f"Поток #{stream.id} больше недоступен для офферов.")
            if len({offer.offer_id for offer in desired}) != len(desired) or (
                desired
                and (
                    any(offer.share < 0 for offer in desired)
                    or sum(offer.share for offer in desired) != 100
                )
            ):
                raise DraftError(f"Проверьте офферы и доли в потоке #{stream.id}.")
            pending.append((stream, baseline, desired))
        if not pending and not cleanup:
            return

        remote_streams = {
            stream.id: stream for stream in list_campaign_streams(keitaro, campaign_id)
        }
        for stream, removed_ids in cleanup:
            remote = remote_streams.get(stream.id)
            if remote is not None and any(
                offer.offer_id in removed_ids for offer in remote.offers
            ):
                raise DraftError(
                    f"Удалённый оффер снова появился в потоке #{stream.id} в Keitaro. "
                    "Обновите офферы перед синхронизацией."
                )
        updates = []
        for stream, baseline, desired in pending:
            remote = remote_streams.get(stream.id)
            if remote is None or not is_offer_stream(remote):
                raise DraftError(f"Поток #{stream.id} больше недоступен для офферов.")
            already_applied = _assignment_signature(
                remote.offers
            ) == _assignment_signature(desired)
            if not already_applied and _assignment_signature(
                remote.offers
            ) != _assignment_signature(baseline):
                raise DraftError(
                    f"Офферы в потоке #{stream.id} изменились в Keitaro. "
                    "Обновите их и проверьте локальные правки перед синхронизацией."
                )
            updates.append((stream, desired, already_applied))

        applied = []
        for stream, desired, already_applied in updates:
            try:
                confirmed = (
                    desired
                    if already_applied
                    else replace_stream_offers(keitaro, stream.id, desired)
                )
                if _assignment_signature(confirmed) != _assignment_signature(desired):
                    raise KeitaroError(
                        "Keitaro вернул другой список офферов после записи."
                    )
            except KeitaroError as exc:
                logger.warning(
                    "Sync unconfirmed request_id=%s campaign=%d stream=%d confirmed_streams=%s",
                    request_id.get(),
                    campaign_id,
                    stream.id,
                    applied,
                )
                if applied:
                    self.snapshot = snapshot.model_dump()
                    db.commit()
                progress = (
                    f" Подтверждены потоки {', '.join(str(item) for item in applied)}."
                    if applied
                    else ""
                )
                raise KeitaroError(
                    f"Поток #{stream.id}: синхронизация не подтверждена. {exc}{progress}"
                ) from exc
            stream.published_offers = confirmed
            stream.edited = False
            stream.offers = [
                offer for offer in stream.offers if offer.is_selected_for_publication
            ]
            for offer in stream.offers:
                offer.state = "active"
            applied.append(stream.id)
        for stream, removed_ids in cleanup:
            stream.offers = [
                offer for offer in stream.offers if offer.offer_id not in removed_ids
            ]
        self.snapshot = snapshot.model_dump()
        db.commit()
        logger.info(
            "Draft synchronized request_id=%s campaign=%d confirmed_streams=%s",
            request_id.get(),
            campaign_id,
            applied,
        )


def _assignment_signature(offers: list[StreamOffer]) -> list[tuple[int, int, str]]:
    return sorted((offer.offer_id, offer.share, offer.state) for offer in offers)


def _require_editable_campaign(keitaro: KeitaroClient, campaign_id: int) -> None:
    campaign = get_campaign(keitaro, campaign_id)
    if campaign.state not in {"active", "disabled"}:
        raise DraftError("Кампания недоступна для редактирования.")


def _fetch_snapshot(keitaro: KeitaroClient, campaign_id: int) -> DraftSnapshot:
    streams, names = fetch_streams_with_offer_names(keitaro, campaign_id)
    return DraftSnapshot.from_streams(streams, names or {})


def _find_offer_name(keitaro: KeitaroClient, offer_id: int) -> str | None:
    matches = search_offers(keitaro, str(offer_id))
    return matches[0].name if matches else None
