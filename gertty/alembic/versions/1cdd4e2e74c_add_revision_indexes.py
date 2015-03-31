"""add revision indexes

Revision ID: 1cdd4e2e74c
Revises: 4a802b741d2f
Create Date: 2015-03-10 16:17:41.330825

"""

# revision identifiers, used by Alembic.
revision = '1cdd4e2e74c'
down_revision = '4a802b741d2f'

from alembic import op


def upgrade():
    op.create_index(op.f('ix_revision_commit'), 'revision', ['commit'])
    op.create_index(op.f('ix_revision_parent'), 'revision', ['parent'])


def downgrade():
    pass
