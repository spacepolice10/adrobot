from typing import Annotated

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from adrobot.keitaro.client import KeitaroClient, KeitaroError

SEARCH_LIMIT = 10


class OfferSummary(BaseModel):
    id: Annotated[int, Field(strict=True, gt=0)]
    name: str


class CatalogOffer(OfferSummary):
    state: str | None = None


catalog = TypeAdapter(list[CatalogOffer])


def list_offers(keitaro: KeitaroClient) -> list[CatalogOffer]:
    try:
        return catalog.validate_python(keitaro.request_json("GET", "offers"))
    except ValidationError as exc:
        raise KeitaroError("Keitaro returned an invalid offer list") from exc


def search_offers(keitaro: KeitaroClient, query: str) -> list[OfferSummary]:
    query = query.strip().casefold()
    if not query:
        return []

    if query.isascii() and query.isdecimal():
        offer_id = query.lstrip("0")
        if not offer_id:
            return []
        try:
            offer = CatalogOffer.model_validate(
                keitaro.request_json("GET", f"offers/{offer_id}")
            )
        except KeitaroError as exc:
            if exc.status_code != 404:
                raise
            return []
        except ValidationError as exc:
            raise KeitaroError("Keitaro returned an invalid offer") from exc

        if str(offer.id) != offer_id:
            raise KeitaroError("Keitaro returned an unexpected offer ID")
        if offer.state == "deleted":
            return []
        return [OfferSummary(id=offer.id, name=offer.name)]

    offers = list_offers(keitaro)
    matches = [
        offer
        for offer in offers
        if offer.state != "deleted" and query in offer.name.casefold()
    ]
    return [
        OfferSummary(id=offer.id, name=offer.name) for offer in matches[:SEARCH_LIMIT]
    ]


def create_external_offer(
    keitaro: KeitaroClient, *, name: str, url: str, notes: str
) -> CatalogOffer:
    result = keitaro.request_json(
        "POST",
        "offers",
        json={
            "name": name,
            "offer_type": "external",
            "action_type": "http",
            "action_payload": url,
            "state": "active",
            "notes": notes,
        },
    )
    try:
        return CatalogOffer.model_validate(result)
    except ValidationError as exc:
        raise KeitaroError(
            "Keitaro принял запрос, но не вернул ID оффера. Проверьте каталог перед повтором."
        ) from exc
