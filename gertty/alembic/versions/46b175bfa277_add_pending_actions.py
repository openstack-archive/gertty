"""add pending actions

Revision ID: 46b175bfa277
Revises: 3d429503a29a
Create Date: 2014-08-31 09:20:11.789330

"""

# revision identifiers, used by Alembic.
revision = '46b175bfa277'
down_revision = '3d429503a29a'

import warnings

from alembic import op
import sqlalchemy as sa

from gertty.dbsupport import sqlite_alter_columns


def upgrade():
    op.create_table('branch',
    sa.Column('key', sa.Integer(), nullable=False),
    sa.Column('project_key', sa.Integer(), sa.ForeignKey('project.key'), index=True, nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('pending_cherry_pick',
    sa.Column('key', sa.Integer(), nullable=False),
    sa.Column('revision_key', sa.Integer(), sa.ForeignKey('revision.key'), index=True, nullable=False),
    sa.Column('branch', sa.String(length=255), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        op.add_column('change', sa.Column('pending_rebase', sa.Boolean()))
        op.add_column('change', sa.Column('pending_topic', sa.Boolean()))
        op.add_column('change', sa.Column('pending_status', sa.Boolean()))
        op.add_column('change', sa.Column('pending_status_message', sa.Text()))
        op.add_column('revision', sa.Column('pending_message', sa.Boolean()))

    connection = op.get_bind()
    change = sa.sql.table('change',
                          sa.sql.column('pending_rebase', sa.Boolean()),
                          sa.sql.column('pending_topic', sa.Boolean()),
                          sa.sql.column('pending_status', sa.Boolean()))
    connection.execute(change.update().values({'pending_rebase':False,
                                               'pending_topic':False,
                                               'pending_status':False}))
    revision = sa.sql.table('revision',
                            sa.sql.column('pending_message', sa.Boolean()))
    connection.execute(revision.update().values({'pending_message':False}))

    sqlite_alter_columns('change', [
        sa.Column('pending_rebase', sa.Boolean(), index=True, nullable=False),
        sa.Column('pending_topic', sa.Boolean(), index=True, nullable=False),
        sa.Column('pending_status', sa.Boolean(), index=True, nullable=False),
        ])
    sqlite_alter_columns('revision', [
        sa.Column('pending_message', sa.Boolean(), index=True, nullable=False),
        ])

def downgrade():
    pass
