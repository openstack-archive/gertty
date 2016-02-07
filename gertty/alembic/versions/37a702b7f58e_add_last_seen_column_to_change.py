"""add last_seen column to change

Revision ID: 37a702b7f58e
Revises: 3610c2543e07
Create Date: 2016-02-06 09:09:38.728225

"""

# revision identifiers, used by Alembic.
revision = '37a702b7f58e'
down_revision = '3610c2543e07'

import warnings

from alembic import op
import sqlalchemy as sa


def upgrade():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        op.add_column('change', sa.Column('last_seen', sa.DateTime, index=True))


def downgrade():
    pass
