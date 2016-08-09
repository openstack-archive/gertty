"""add change.outdated

Revision ID: 7ef7dfa2ca3a
Revises: 37a702b7f58e
Create Date: 2016-08-09 08:59:04.441926

"""

# revision identifiers, used by Alembic.
revision = '7ef7dfa2ca3a'
down_revision = '37a702b7f58e'

import warnings

from alembic import op
import sqlalchemy as sa

from gertty.dbsupport import sqlite_alter_columns


def upgrade():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        op.add_column('change', sa.Column('outdated', sa.Boolean()))

    connection = op.get_bind()
    change = sa.sql.table('change',
                          sa.sql.column('outdated', sa.Boolean()))
    connection.execute(change.update().values({'outdated':False}))

    sqlite_alter_columns('change', [
        sa.Column('outdated', sa.Boolean(), index=True, nullable=False),
        ])


def downgrade():
    pass
