"""add held

Revision ID: 3cc7e3753dc3
Revises: 1cdd4e2e74c
Create Date: 2015-03-22 08:48:15.516289

"""

# revision identifiers, used by Alembic.
revision = '3cc7e3753dc3'
down_revision = '1cdd4e2e74c'

import warnings

from alembic import op
import sqlalchemy as sa

from gertty.dbsupport import sqlite_alter_columns


def upgrade():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        op.add_column('change', sa.Column('held', sa.Boolean()))

    connection = op.get_bind()
    change = sa.sql.table('change',
                          sa.sql.column('held', sa.Boolean()))
    connection.execute(change.update().values({'held':False}))

    sqlite_alter_columns('change', [
        sa.Column('held', sa.Boolean(), index=True, nullable=False),
        ])


def downgrade():
    pass
