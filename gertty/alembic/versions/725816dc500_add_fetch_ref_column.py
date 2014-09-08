"""Add fetch ref column

Revision ID: 725816dc500
Revises: 38104b4c1b84
Create Date: 2014-05-31 14:51:08.078616

"""

# revision identifiers, used by Alembic.
revision = '725816dc500'
down_revision = '38104b4c1b84'

import warnings

from alembic import op
import sqlalchemy as sa

from gertty.dbsupport import sqlite_alter_columns


def upgrade():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        op.add_column('revision', sa.Column('fetch_auth', sa.Boolean()))
        op.add_column('revision', sa.Column('fetch_ref', sa.String(length=255)))

    conn = op.get_bind()
    res = conn.execute('select r.key, r.number, c.number from revision r, "change" c where r.change_key=c.key')
    for (rkey, rnumber, cnumber) in res.fetchall():
        q = sa.text('update revision set fetch_auth=:auth, fetch_ref=:ref where "key"=:key')
        ref = 'refs/changes/%s/%s/%s' % (str(cnumber)[-2:], cnumber, rnumber)
        res = conn.execute(q, key=rkey, ref=ref, auth=False)

    sqlite_alter_columns('revision', [
        sa.Column('fetch_auth', sa.Boolean(), nullable=False),
        sa.Column('fetch_ref', sa.String(length=255), nullable=False)
        ])

def downgrade():
    op.drop_column('revision', 'fetch_auth')
    op.drop_column('revision', 'fetch_ref')
