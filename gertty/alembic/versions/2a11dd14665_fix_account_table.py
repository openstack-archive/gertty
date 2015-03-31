"""fix account table

Revision ID: 2a11dd14665
Revises: 4cc9c46f9d8b
Create Date: 2014-08-20 13:07:25.079603

"""

# revision identifiers, used by Alembic.
revision = '2a11dd14665'
down_revision = '4cc9c46f9d8b'

from alembic import op


def upgrade():
    op.drop_index('ix_account_name', 'account')
    op.drop_index('ix_account_username', 'account')
    op.drop_index('ix_account_email', 'account')
    op.create_index(op.f('ix_account_name'), 'account', ['name'])
    op.create_index(op.f('ix_account_username'), 'account', ['username'])
    op.create_index(op.f('ix_account_email'), 'account', ['email'])

def downgrade():
    pass
