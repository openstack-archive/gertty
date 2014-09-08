"""Added project updated column

Revision ID: 38104b4c1b84
Revises: 56e48a4a064a
Create Date: 2014-05-31 06:52:12.452205

"""

# revision identifiers, used by Alembic.
revision = '38104b4c1b84'
down_revision = '56e48a4a064a'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('project', sa.Column('updated', sa.DateTime))

    conn = op.get_bind()
    res = conn.execute('select "key", name from project')
    for (key, name) in res.fetchall():
        q = sa.text("select max(updated) from change where project_key=:key")
        res = conn.execute(q, key=key)
        for (updated,) in res.fetchall():
            q = sa.text('update project set updated=:updated where "key"=:key')
            conn.execute(q, key=key, updated=updated)

    op.create_index(op.f('ix_project_updated'), 'project', ['updated'], unique=False)

def downgrade():
    op.drop_index(op.f('ix_project_updated'), table_name='project')
    op.drop_column('project', 'updated')
