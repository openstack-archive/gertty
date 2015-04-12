"""add can_submit column

Revision ID: 312cd5a9f878
Revises: 46b175bfa277
Create Date: 2014-09-18 16:37:13.149729

"""

# revision identifiers, used by Alembic.
revision = '312cd5a9f878'
down_revision = '46b175bfa277'

import warnings

from alembic import op
import sqlalchemy as sa

from gertty.dbsupport import sqlite_alter_columns


def upgrade():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        op.add_column('revision', sa.Column('can_submit', sa.Boolean()))

    conn = op.get_bind()
    q = sa.text('update revision set can_submit=:submit')
    conn.execute(q, submit=False)

    sqlite_alter_columns('revision', [
        sa.Column('can_submit', sa.Boolean(), nullable=False),
        ])


def downgrade():
    pass
