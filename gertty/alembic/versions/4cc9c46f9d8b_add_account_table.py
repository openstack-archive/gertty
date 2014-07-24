"""add account table

Revision ID: 4cc9c46f9d8b
Revises: 725816dc500
Create Date: 2014-07-23 16:01:47.462597

"""

# revision identifiers, used by Alembic.
revision = '4cc9c46f9d8b'
down_revision = '725816dc500'

import warnings

from alembic import op
import sqlalchemy as sa

from gertty.dbsupport import sqlite_alter_columns, sqlite_drop_columns


def upgrade():
    sqlite_drop_columns('message', ['name'])
    sqlite_drop_columns('comment', ['name'])
    sqlite_drop_columns('approval', ['name'])
    sqlite_drop_columns('change', ['owner'])

    op.create_table('account',
    sa.Column('key', sa.Integer(), nullable=False),
    sa.Column('id', sa.Integer(), index=True, unique=True, nullable=False),
    sa.Column('name', sa.String(length=255)),
    sa.Column('username', sa.String(length=255)),
    sa.Column('email', sa.String(length=255)),
    sa.PrimaryKeyConstraint('key')
    )

    op.create_index(op.f('ix_account_name'), 'account', ['name'], unique=True)
    op.create_index(op.f('ix_account_username'), 'account', ['name'], unique=True)
    op.create_index(op.f('ix_account_email'), 'account', ['name'], unique=True)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        op.add_column('message', sa.Column('account_key', sa.Integer()))
        op.add_column('comment', sa.Column('account_key', sa.Integer()))
        op.add_column('approval', sa.Column('account_key', sa.Integer()))
        op.add_column('change', sa.Column('account_key', sa.Integer()))
    sqlite_alter_columns('message', [
            sa.Column('account_key', sa.Integer(), sa.ForeignKey('account.key'))
            ])
    sqlite_alter_columns('comment', [
            sa.Column('account_key', sa.Integer(), sa.ForeignKey('account.key'))
            ])
    sqlite_alter_columns('approval', [
            sa.Column('account_key', sa.Integer(), sa.ForeignKey('account.key'))
            ])
    sqlite_alter_columns('change', [
            sa.Column('account_key', sa.Integer(), sa.ForeignKey('account.key'))
            ])

    op.create_index(op.f('ix_message_account_key'), 'message', ['account_key'], unique=False)
    op.create_index(op.f('ix_comment_account_key'), 'comment', ['account_key'], unique=False)
    op.create_index(op.f('ix_approval_account_key'), 'approval', ['account_key'], unique=False)
    op.create_index(op.f('ix_change_account_key'), 'change', ['account_key'], unique=False)

    connection = op.get_bind()
    project = sa.sql.table('project', sa.sql.column('updated', sa.DateTime))
    connection.execute(project.update().values({'updated':None}))

    approval = sa.sql.table('approval', sa.sql.column('pending'))
    connection.execute(approval.delete().where(approval.c.pending==False))


def downgrade():
    pass
