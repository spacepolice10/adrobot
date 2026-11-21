from alembic import context

from adrobot.db import create_database_engine
from adrobot.models.offer_draft import CampaignOfferDraft
from adrobot.settings import DatabaseSettings

if context.is_offline_mode():
    raise RuntimeError(
        "The draft baseline requires a connection to inspect the existing schema."
    )

engine = create_database_engine(DatabaseSettings(_env_file=".env").database_url)
try:
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=CampaignOfferDraft.metadata
        )
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
