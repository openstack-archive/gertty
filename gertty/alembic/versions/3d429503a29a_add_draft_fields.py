"""add draft fields

Revision ID: 3d429503a29a
Revises: 2a11dd14665
Create Date: 2014-08-30 13:26:03.698902

"""

# revision identifiers, used by Alembic.
revision = '3d429503a29a'
down_revision = '2a11dd14665'

import warnings

from alembic import op
import sqlalchemy as sa

from gertty.dbsupport import sqlite_alter_columns, sqlite_drop_columns

def upgrade():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        op.add_column('message', sa.Column('draft', sa.Boolean()))
        op.add_column('comment', sa.Column('draft', sa.Boolean()))
        op.add_column('approval', sa.Column('draft', sa.Boolean()))

    conn = op.get_bind()
    conn.execute("update message set draft=pending")
    conn.execute("update comment set draft=pending")
    conn.execute("update approval set draft=pending")

    sqlite_alter_columns('message', [
        sa.Column('draft', sa.Boolean(), index=True, nullable=False),
        ])

    sqlite_alter_columns('comment', [
        sa.Column('draft', sa.Boolean(), index=True, nullable=False),
        ])

    sqlite_alter_columns('approval', [
        sa.Column('draft', sa.Boolean(), index=True, nullable=False),
        ])

    sqlite_drop_columns('comment', ['pending'])
    sqlite_drop_columns('approval', ['pending'])


def downgrade():
    pass
