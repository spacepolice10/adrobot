import sys

from dotenv import load_dotenv
from pydantic import ValidationError

from adrobot.keitaro import (
    KeitaroClient,
    KeitaroConfigurationError,
    KeitaroError,
    open_keitaro_client,
)
from adrobot.keitaro.offers import CatalogOffer, create_external_offer, list_offers

TEST_OFFER_NAME = "Adrobot Test Offer 2"


def ensure_test_offer(keitaro: KeitaroClient) -> tuple[CatalogOffer, bool]:
    matches = [
        offer
        for offer in list_offers(keitaro)
        if offer.name == TEST_OFFER_NAME and offer.state != "deleted"
    ]
    if len(matches) > 1:
        raise KeitaroError("В Keitaro уже несколько офферов с таким тестовым именем.")
    if matches:
        return matches[0], False

    offer = create_external_offer(
        keitaro,
        name=TEST_OFFER_NAME,
        url="https://example.com/",
        notes="Тестовый оффер для проверки редактора Adrobot",
    )
    return offer, True


def main() -> int:
    load_dotenv(".env")
    try:
        with open_keitaro_client() as keitaro:
            offer, created = ensure_test_offer(keitaro)
    except (KeitaroConfigurationError, KeitaroError, ValidationError) as exc:
        print(f"Не удалось подтвердить тестовый оффер. {exc}", file=sys.stderr)
        return 1

    status = "Создан" if created else "Уже существует"
    print(f"{status}: #{offer.id} · {offer.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
