"""add query sync table

Revision ID: 1bb187bcd401
Revises: 3cc7e3753dc3
Create Date: 2015-03-26 07:32:33.584657

"""

# revision identifiers, used by Alembic.
revision = '1bb187bcd401'
down_revision = '3cc7e3753dc3'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table('sync_query',
    sa.Column('key', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(255), index=True, unique=True, nullable=False),
    sa.Column('updated', sa.DateTime, index=True),
    sa.PrimaryKeyConstraint('key')
    )

def downgrade():
    pass
