"""add starred

Revision ID: 4a802b741d2f
Revises: 312cd5a9f878
Create Date: 2015-02-12 18:10:19.187733

"""

# revision identifiers, used by Alembic.
revision = '4a802b741d2f'
down_revision = '312cd5a9f878'

import warnings

from alembic import op
import sqlalchemy as sa

from gertty.dbsupport import sqlite_alter_columns


def upgrade():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        op.add_column('change', sa.Column('starred', sa.Boolean()))
        op.add_column('change', sa.Column('pending_starred', sa.Boolean()))

    connection = op.get_bind()
    change = sa.sql.table('change',
                          sa.sql.column('starred', sa.Boolean()),
                          sa.sql.column('pending_starred', sa.Boolean()))
    connection.execute(change.update().values({'starred':False,
                                               'pending_starred':False}))

    sqlite_alter_columns('change', [
        sa.Column('starred', sa.Boolean(), index=True, nullable=False),
        sa.Column('pending_starred', sa.Boolean(), index=True, nullable=False),
        ])


def downgrade():
    pass
