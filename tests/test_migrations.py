import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select

from adrobot.db import create_database_engine
from adrobot.models.offer_draft import CampaignOfferDraft


def test_migrations_adopt_existing_drafts_and_upgrade_empty_database(
    tmp_path, monkeypatch
):
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    engine = create_database_engine(url)
    table = CampaignOfferDraft.__table__
    config = Config("alembic.ini")
    snapshot = {"streams": [{"id": 99}]}
    try:
        with engine.begin() as conn:
            table.create(conn)
            conn.execute(table.insert().values(campaign_id=42, snapshot=snapshot))
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        with engine.connect() as conn:
            assert conn.scalar(select(table.c.snapshot)) == snapshot
        command.downgrade(config, "base")
        assert not inspect(engine).has_table(table.name)
        command.upgrade(config, "head")
        assert inspect(engine).has_table(table.name)
    finally:
        engine.dispose()


def test_incompatible_legacy_table_remains_intact(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'unexpected.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    engine = create_database_engine(url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE campaign_offer_drafts (original TEXT)"
            )
            connection.exec_driver_sql(
                "INSERT INTO campaign_offer_drafts VALUES ('keep')"
            )
        with pytest.raises(RuntimeError, match="differs from the baseline"):
            command.upgrade(Config("alembic.ini"), "head")
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    "SELECT original FROM campaign_offer_drafts"
                ).scalar_one()
                == "keep"
            )
    finally:
        engine.dispose()
