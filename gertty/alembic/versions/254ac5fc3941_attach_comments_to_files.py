"""attach comments to files

Revision ID: 254ac5fc3941
Revises: 50344aecd1c2
Create Date: 2015-04-13 15:52:07.104397

"""

# revision identifiers, used by Alembic.
revision = '254ac5fc3941'
down_revision = '50344aecd1c2'

import sys
import warnings

from alembic import op
import sqlalchemy as sa

from gertty.dbsupport import sqlite_alter_columns, sqlite_drop_columns


def upgrade():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        op.add_column('comment', sa.Column('file_key', sa.Integer()))
    sqlite_alter_columns('comment', [
            sa.Column('file_key', sa.Integer(), sa.ForeignKey('file.key'))
            ])

    update_query = sa.text('update comment set file_key=:file_key where key=:key')
    file_query = sa.text('select f.key from file f where f.revision_key=:revision_key and f.path=:path')

    file_insert_query = sa.text('insert into file (key, revision_key, path, old_path, status, inserted, deleted) '
                                ' values (NULL, :revision_key, :path, NULL, NULL, NULL, NULL)')

    conn = op.get_bind()

    countres = conn.execute('select count(*) from comment')
    comments = countres.fetchone()[0]

    comment_res = conn.execute('select p.name, c.number, c.status, r.key, r.number, m.file, m.key '
                               'from project p, change c, revision r, comment m '
                               'where m.revision_key=r.key and r.change_key=c.key and '
                               'c.project_key=p.key order by p.name')

    count = 0
    for (pname, cnumber, cstatus, rkey, rnumber, mfile, mkey) in comment_res.fetchall():
        count += 1
        sys.stdout.write('Comment %s / %s\r' % (count, comments))
        sys.stdout.flush()

        file_res = conn.execute(file_query, revision_key=rkey, path=mfile)
        file_key = file_res.fetchone()
        if not file_key:
            conn.execute(file_insert_query, revision_key=rkey, path=mfile)
            file_res = conn.execute(file_query, revision_key=rkey, path=mfile)
            file_key = file_res.fetchone()
        fkey = file_key[0]
        file_res = conn.execute(update_query, file_key=fkey, key=mkey)
    sqlite_drop_columns('comment', ['revision_key', 'file'])
    print

def downgrade():
    pass
