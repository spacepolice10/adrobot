"""Create the offer draft table or adopt the original unversioned schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001_offer_drafts"
down_revision = None
branch_labels = None
depends_on = None

TABLE = "campaign_offer_drafts"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(TABLE):
        columns = {column["name"]: column for column in inspector.get_columns(TABLE)}
        if (
            columns.keys() != {"campaign_id", "snapshot"}
            or not isinstance(columns["campaign_id"]["type"], sa.BigInteger)
            or not isinstance(columns["snapshot"]["type"], sa.JSON)
            or any(column["nullable"] for column in columns.values())
            or inspector.get_pk_constraint(TABLE)["constrained_columns"]
            != ["campaign_id"]
        ):
            raise RuntimeError(
                "Existing campaign_offer_drafts schema differs from the baseline"
            )
        return
    op.create_table(
        TABLE,
        sa.Column(
            "campaign_id", sa.BigInteger(), primary_key=True, autoincrement=False
        ),
        sa.Column("snapshot", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table(TABLE)
