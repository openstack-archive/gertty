"""add files table

Revision ID: 50344aecd1c2
Revises: 1bb187bcd401
Create Date: 2015-04-13 08:08:08.682803

"""

# revision identifiers, used by Alembic.
revision = '50344aecd1c2'
down_revision = '1bb187bcd401'

import re
import sys

from alembic import op, context
import sqlalchemy as sa
import git.exc

import gertty.db
import gertty.gitrepo

def upgrade():
    op.create_table('file',
    sa.Column('key', sa.Integer(), nullable=False),
    sa.Column('revision_key', sa.Integer(), nullable=False, index=True),
    sa.Column('path', sa.Text(), nullable=False, index=True),
    sa.Column('old_path', sa.Text(), index=True),
    sa.Column('status', sa.String(length=1)),
    sa.Column('inserted', sa.Integer()),
    sa.Column('deleted', sa.Integer()),
    sa.PrimaryKeyConstraint('key')
    )

    pathre = re.compile('((.*?)\{|^)(.*?) => (.*?)(\}(.*)|$)')
    insert = sa.text('insert into file (key, revision_key, path, old_path, status, inserted, deleted) '
                     ' values (NULL, :revision_key, :path, :old_path, :status, :inserted, :deleted)')

    conn = op.get_bind()

    countres = conn.execute('select count(*) from revision')
    revisions = countres.fetchone()[0]
    if revisions > 50:
        print('')
        print('Adding support for searching for changes by file modified.  '
              'This may take a while.')

    qres = conn.execute('select p.name, c.number, c.status, r.key, r.number, r."commit", r.parent from project p, change c, revision r '
                        'where r.change_key=c.key and c.project_key=p.key order by p.name')

    count = 0
    for (pname, cnumber, cstatus, rkey, rnumber, commit, parent) in qres.fetchall():
        count += 1
        sys.stdout.write('Diffstat revision %s / %s\r' % (count, revisions))
        sys.stdout.flush()
        ires = conn.execute(insert, revision_key=rkey, path='/COMMIT_MSG', old_path=None,
                            status=None, inserted=None, deleted=None)
        repo = gertty.gitrepo.get_repo(pname, context.config.gertty_app.config)
        try:
            stats = repo.diffstat(parent, commit)
        except git.exc.GitCommandError:
            # Probably a missing commit
            if cstatus not in ['MERGED', 'ABANDONED']:
                print("Unable to examine diff for %s %s change %s,%s" % (cstatus, pname, cnumber, rnumber))
            continue
        for stat in stats:
            try:
                (added, removed, path) = stat
            except ValueError:
                if cstatus not in ['MERGED', 'ABANDONED']:
                    print("Empty diffstat for %s %s change %s,%s" % (cstatus, pname, cnumber, rnumber))
            m = pathre.match(path)
            status = gertty.db.File.STATUS_MODIFIED
            old_path = None
            if m:
                status = gertty.db.File.STATUS_RENAMED
                pre = m.group(2) or ''
                post = m.group(6) or ''
                old_path = pre+m.group(3)+post
                path = pre+m.group(4)+post
            try:
                added = int(added)
            except ValueError:
                added = None
            try:
                removed = int(removed)
            except ValueError:
                removed = None
            conn.execute(insert, revision_key=rkey, path=path, old_path=old_path,
                         status=status, inserted=added, deleted=removed)
    print('')

def downgrade():
    pass
