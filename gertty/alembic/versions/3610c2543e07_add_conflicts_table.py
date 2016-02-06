"""add conflicts table

Revision ID: 3610c2543e07
Revises: 4388de50824a
Create Date: 2016-02-05 16:43:20.047238

"""

# revision identifiers, used by Alembic.
revision = '3610c2543e07'
down_revision = '4388de50824a'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table('change_conflict',
    sa.Column('key', sa.Integer(), nullable=False),
    sa.Column('change1_key', sa.Integer(), sa.ForeignKey('change.key'), index=True),
    sa.Column('change2_key', sa.Integer(), sa.ForeignKey('change.key'), index=True),
    sa.PrimaryKeyConstraint('key')
    )


def downgrade():
    pass
