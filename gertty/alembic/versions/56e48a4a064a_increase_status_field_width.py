"""Increase status field width

Revision ID: 56e48a4a064a
Revises: 44402069e137
Create Date: 2014-05-05 11:49:42.133569

"""

# revision identifiers, used by Alembic.
revision = '56e48a4a064a'
down_revision = '44402069e137'

import sqlalchemy as sa

from gertty.dbsupport import sqlite_alter_columns

def upgrade():
    sqlite_alter_columns('change', [
        sa.Column('status', sa.String(16), index=True, nullable=False)
        ])


def downgrade():
    sqlite_alter_columns('change', [
        sa.Column('status', sa.String(8), index=True, nullable=False)
        ])
