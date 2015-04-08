# Copyright 2014 OpenStack Foundation
# Copyright 2014 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import re
import time
import logging
import threading

import alembic
import alembic.config
import sqlalchemy
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.schema import ForeignKey
from sqlalchemy.orm import mapper, sessionmaker, relationship, scoped_session
from sqlalchemy.orm.session import Session
from sqlalchemy.sql import exists
from sqlalchemy.sql.expression import and_

metadata = MetaData()
project_table = Table(
    'project', metadata,
    Column('key', Integer, primary_key=True),
    Column('name', String(255), index=True, unique=True, nullable=False),
    Column('subscribed', Boolean, index=True, default=False),
    Column('description', Text, nullable=False, default=''),
    Column('updated', DateTime, index=True),
    )
branch_table = Table(
    'branch', metadata,
    Column('key', Integer, primary_key=True),
    Column('project_key', Integer, ForeignKey("project.key"), index=True),
    Column('name', String(255), index=True, nullable=False),
    )
change_table = Table(
    'change', metadata,
    Column('key', Integer, primary_key=True),
    Column('project_key', Integer, ForeignKey("project.key"), index=True),
    Column('id', String(255), index=True, unique=True, nullable=False),
    Column('number', Integer, index=True, unique=True, nullable=False),
    Column('branch', String(255), index=True, nullable=False),
    Column('change_id', String(255), index=True, nullable=False),
    Column('topic', String(255), index=True),
    Column('account_key', Integer, ForeignKey("account.key"), index=True),
    Column('subject', Text, nullable=False),
    Column('created', DateTime, index=True, nullable=False),
    Column('updated', DateTime, index=True, nullable=False),
    Column('status', String(16), index=True, nullable=False),
    Column('hidden', Boolean, index=True, nullable=False),
    Column('reviewed', Boolean, index=True, nullable=False),
    Column('starred', Boolean, index=True, nullable=False),
    Column('held', Boolean, index=True, nullable=False),
    Column('pending_rebase', Boolean, index=True, nullable=False),
    Column('pending_topic', Boolean, index=True, nullable=False),
    Column('pending_starred', Boolean, index=True, nullable=False),
    Column('pending_status', Boolean, index=True, nullable=False),
    Column('pending_status_message', Text),
    )
revision_table = Table(
    'revision', metadata,
    Column('key', Integer, primary_key=True),
    Column('change_key', Integer, ForeignKey("change.key"), index=True),
    Column('number', Integer, index=True, nullable=False),
    Column('message', Text, nullable=False),
    Column('commit', String(255), index=True, nullable=False),
    Column('parent', String(255), index=True, nullable=False),
    # TODO: fetch_ref, fetch_auth are unused; remove
    Column('fetch_auth', Boolean, nullable=False),
    Column('fetch_ref', String(255), nullable=False),
    Column('pending_message', Boolean, index=True, nullable=False),
    Column('can_submit', Boolean, nullable=False),
    )
message_table = Table(
    'message', metadata,
    Column('key', Integer, primary_key=True),
    Column('revision_key', Integer, ForeignKey("revision.key"), index=True),
    Column('account_key', Integer, ForeignKey("account.key"), index=True),
    Column('id', String(255), index=True), #, unique=True, nullable=False),
    Column('created', DateTime, index=True, nullable=False),
    Column('message', Text, nullable=False),
    Column('draft', Boolean, index=True, nullable=False),
    Column('pending', Boolean, index=True, nullable=False),
    )
comment_table = Table(
    'comment', metadata,
    Column('key', Integer, primary_key=True),
    Column('file_key', Integer, ForeignKey("file.key"), index=True),
    Column('account_key', Integer, ForeignKey("account.key"), index=True),
    Column('id', String(255), index=True), #, unique=True, nullable=False),
    Column('in_reply_to', String(255)),
    Column('created', DateTime, index=True, nullable=False),
    Column('parent', Boolean, nullable=False),
    Column('line', Integer),
    Column('message', Text, nullable=False),
    Column('draft', Boolean, index=True, nullable=False),
    )
label_table = Table(
    'label', metadata,
    Column('key', Integer, primary_key=True),
    Column('change_key', Integer, ForeignKey("change.key"), index=True),
    Column('category', String(255), nullable=False),
    Column('value', Integer, nullable=False),
    Column('description', String(255), nullable=False),
    )
permitted_label_table = Table(
    'permitted_label', metadata,
    Column('key', Integer, primary_key=True),
    Column('change_key', Integer, ForeignKey("change.key"), index=True),
    Column('category', String(255), nullable=False),
    Column('value', Integer, nullable=False),
    )
approval_table = Table(
    'approval', metadata,
    Column('key', Integer, primary_key=True),
    Column('change_key', Integer, ForeignKey("change.key"), index=True),
    Column('account_key', Integer, ForeignKey("account.key"), index=True),
    Column('category', String(255), nullable=False),
    Column('value', Integer, nullable=False),
    Column('draft', Boolean, index=True, nullable=False),
    )
account_table = Table(
    'account', metadata,
    Column('key', Integer, primary_key=True),
    Column('id', Integer, index=True, unique=True, nullable=False),
    Column('name', String(255), index=True),
    Column('username', String(255), index=True),
    Column('email', String(255), index=True),
    )
pending_cherry_pick_table = Table(
    'pending_cherry_pick', metadata,
    Column('key', Integer, primary_key=True),
    Column('revision_key', Integer, ForeignKey("revision.key"), index=True),
    # Branch is a str here to avoid FK complications if the branch
    # entry is removed.
    Column('branch', String(255), nullable=False),
    Column('message', Text, nullable=False),
    )
sync_query_table = Table(
    'sync_query', metadata,
    Column('key', Integer, primary_key=True),
    Column('name', String(255), index=True, unique=True, nullable=False),
    Column('updated', DateTime, index=True),
    )
file_table = Table(
    'file', metadata,
    Column('key', Integer, primary_key=True),
    Column('revision_key', Integer, ForeignKey("revision.key"), index=True),
    Column('path', Text, nullable=False, index=True),
    Column('old_path', Text, index=True),
    Column('inserted', Integer),
    Column('deleted', Integer),
    Column('status', String(1), nullable=False),
    )


class Account(object):
    def __init__(self, id, name=None, username=None, email=None):
        self.id = id
        self.name = name
        self.username = username
        self.email = email

class Project(object):
    def __init__(self, name, subscribed=False, description=''):
        self.name = name
        self.subscribed = subscribed
        self.description = description

    def createChange(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        c = Change(*args, **kw)
        self.changes.append(c)
        session.add(c)
        session.flush()
        return c

    def createBranch(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        b = Branch(*args, **kw)
        self.branches.append(b)
        session.add(b)
        session.flush()
        return b

class Branch(object):
    def __init__(self, project, name):
        self.project_key = project.key
        self.name = name

class Change(object):
    def __init__(self, project, id, owner, number, branch, change_id,
                 subject, created, updated, status, topic=None,
                 hidden=False, reviewed=False, starred=False, held=False,
                 pending_rebase=False, pending_topic=False,
                 pending_starred=False, pending_status=False,
                 pending_status_message=None):
        self.project_key = project.key
        self.account_key = owner.key
        self.id = id
        self.number = number
        self.branch = branch
        self.change_id = change_id
        self.topic = topic
        self.subject = subject
        self.created = created
        self.updated = updated
        self.status = status
        self.hidden = hidden
        self.reviewed = reviewed
        self.starred = starred
        self.held = held
        self.pending_rebase = pending_rebase
        self.pending_topic = pending_topic
        self.pending_starred = pending_starred
        self.pending_status = pending_status
        self.pending_status_message = pending_status_message

    def getCategories(self):
        categories = set([label.category for label in self.labels])
        return sorted(categories)

    def getMaxForCategory(self, category):
        if not hasattr(self, '_approval_cache'):
            self._updateApprovalCache()
        return self._approval_cache.get(category, 0)

    def _updateApprovalCache(self):
        cat_min = {}
        cat_max = {}
        cat_value = {}
        for approval in self.approvals:
            if approval.draft:
                continue
            cur_min = cat_min.get(approval.category, 0)
            cur_max = cat_max.get(approval.category, 0)
            cur_min = min(approval.value, cur_min)
            cur_max = max(approval.value, cur_max)
            cat_min[approval.category] = cur_min
            cat_max[approval.category] = cur_max
            cur_value = cat_value.get(approval.category, 0)
            if abs(cur_min) > abs(cur_value):
                cur_value = cur_min
            if abs(cur_max) > abs(cur_value):
                cur_value = cur_max
            cat_value[approval.category] = cur_value
        self._approval_cache = cat_value

    def getMinMaxPermittedForCategory(self, category):
        if not hasattr(self, '_permitted_cache'):
            self._updatePermittedCache()
        return self._permitted_cache.get(category, (0,0))

    def _updatePermittedCache(self):
        cache = {}
        for label in self.labels:
            if label.category not in cache:
                cache[label.category] = [0, 0]
            if label.value > cache[label.category][1]:
                cache[label.category][1] = label.value
            if label.value < cache[label.category][0]:
                cache[label.category][0] = label.value
        self._permitted_cache = cache

    def createRevision(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        r = Revision(*args, **kw)
        self.revisions.append(r)
        session.add(r)
        session.flush()
        return r

    def createLabel(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        l = Label(*args, **kw)
        self.labels.append(l)
        session.add(l)
        session.flush()
        return l

    def createApproval(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        l = Approval(*args, **kw)
        self.approvals.append(l)
        session.add(l)
        session.flush()
        return l

    def createPermittedLabel(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        l = PermittedLabel(*args, **kw)
        self.permitted_labels.append(l)
        session.add(l)
        session.flush()
        return l

    @property
    def owner_name(self):
        owner_name = 'Anonymous Coward'
        if self.owner:
            if self.owner.name:
                owner_name = self.owner.name
            elif self.owner.username:
                owner_name = self.owner.username
            elif self.owner.email:
                owner_name = self.owner.email
        return owner_name


class Revision(object):
    def __init__(self, change, number, message, commit, parent,
                 fetch_auth, fetch_ref, pending_message=False,
                 can_submit=False):
        self.change_key = change.key
        self.number = number
        self.message = message
        self.commit = commit
        self.parent = parent
        self.fetch_auth = fetch_auth
        self.fetch_ref = fetch_ref
        self.pending_message = pending_message
        self.can_submit = can_submit

    def createMessage(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        m = Message(*args, **kw)
        self.messages.append(m)
        session.add(m)
        session.flush()
        return m

    def createPendingCherryPick(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        c = PendingCherryPick(*args, **kw)
        self.pending_cherry_picks.append(c)
        session.add(c)
        session.flush()
        return c

    def createFile(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        f = File(*args, **kw)
        self.files.append(f)
        session.add(f)
        session.flush()
        if hasattr(self, '_file_cache'):
            self._file_cache[f.path] = f
        return f

    def getFile(self, path):
        if not hasattr(self, '_file_cache'):
            self._file_cache = {}
            for f in self.files:
                self._file_cache[f.path] = f
        return self._file_cache.get(path, None)

    def getPendingMessage(self):
        for m in self.messages:
            if m.pending:
                return m
        return None

    def getDraftMessage(self):
        for m in self.messages:
            if m.draft:
                return m
        return None


class Message(object):
    def __init__(self, revision, id, author, created, message, draft=False, pending=False):
        self.revision_key = revision.key
        self.account_key = author.key
        self.id = id
        self.created = created
        self.message = message
        self.draft = draft
        self.pending = pending

    @property
    def author_name(self):
        author_name = 'Anonymous Coward'
        if self.author:
            if self.author.name:
                author_name = self.author.name
            elif self.author.username:
                author_name = self.author.username
            elif self.author.email:
                author_name = self.author.email
        return author_name

class Comment(object):
    def __init__(self, file, id, author, in_reply_to, created, parent, line, message, draft=False):
        self.file_key = file.key
        self.account_key = author.key
        self.id = id
        self.in_reply_to = in_reply_to
        self.created = created
        self.parent = parent
        self.line = line
        self.message = message
        self.draft = draft

class Label(object):
    def __init__(self, change, category, value, description):
        self.change_key = change.key
        self.category = category
        self.value = value
        self.description = description

class PermittedLabel(object):
    def __init__(self, change, category, value):
        self.change_key = change.key
        self.category = category
        self.value = value

class Approval(object):
    def __init__(self, change, reviewer, category, value, draft=False):
        self.change_key = change.key
        self.account_key = reviewer.key
        self.category = category
        self.value = value
        self.draft = draft

class PendingCherryPick(object):
    def __init__(self, revision, branch, message):
        self.revision_key = revision.key
        self.branch = branch
        self.message = message

class SyncQuery(object):
    def __init__(self, name):
        self.name = name

class File(object):
    STATUS_ADDED = 'A'
    STATUS_DELETED = 'D'
    STATUS_RENAMED = 'R'
    STATUS_COPIED = 'C'
    STATUS_REWRITTEN = 'W'
    STATUS_MODIFIED = 'M'

    def __init__(self, revision, path, status, old_path=None,
                 inserted=None, deleted=None):
        self.revision_key = revision.key
        self.path = path
        self.status = status
        self.old_path = old_path
        self.inserted = inserted
        self.deleted = deleted

    @property
    def display_path(self):
        if not self.old_path:
            return self.path
        pre = []
        post = []
        for start in range(min(len(self.old_path), len(self.path))):
            if self.path[start] == self.old_path[start]:
                pre.append(self.old_path[start])
            else:
                break
        pre = ''.join(pre)
        for end in range(1, min(len(self.old_path), len(self.path))-1):
            if self.path[0-end] == self.old_path[0-end]:
                post.insert(0, self.old_path[0-end])
            else:
                break
        post = ''.join(post)
        mid = '{%s => %s}' % (self.old_path[start:0-end+1], self.path[start:0-end+1])
        if pre and post:
            mid = '{%s => %s}' % (self.old_path[start:0-end+1],
                                  self.path[start:0-end+1])
            return pre + mid + post
        else:
            return '%s => %s' % (self.old_path, self.path)

    def createComment(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        c = Comment(*args, **kw)
        self.comments.append(c)
        session.add(c)
        session.flush()
        return c


mapper(Account, account_table)
mapper(Project, project_table, properties=dict(
        branches=relationship(Branch, backref='project',
                              order_by=branch_table.c.name,
                              cascade='all, delete-orphan'),
        changes=relationship(Change, backref='project',
                             order_by=change_table.c.number,
                             cascade='all, delete-orphan'),
        unreviewed_changes=relationship(Change,
                                        primaryjoin=and_(project_table.c.key==change_table.c.project_key,
                                                         change_table.c.hidden==False,
                                                         change_table.c.status!='MERGED',
                                                         change_table.c.status!='ABANDONED',
                                                         change_table.c.reviewed==False),
                                        order_by=change_table.c.number,
                                        ),
        open_changes=relationship(Change,
                                  primaryjoin=and_(project_table.c.key==change_table.c.project_key,
                                                   change_table.c.status!='MERGED',
                                                   change_table.c.status!='ABANDONED'),
                                  order_by=change_table.c.number,
                                  ),
        ))
mapper(Branch, branch_table)
mapper(Change, change_table, properties=dict(
        owner=relationship(Account),
        revisions=relationship(Revision, backref='change',
                               order_by=revision_table.c.number,
                               cascade='all, delete-orphan'),
        messages=relationship(Message,
                              secondary=revision_table,
                              order_by=message_table.c.created,
                              viewonly=True),
        labels=relationship(Label, backref='change',
                            order_by=(label_table.c.category, label_table.c.value),
                            cascade='all, delete-orphan'),
        permitted_labels=relationship(PermittedLabel, backref='change',
                                      order_by=(permitted_label_table.c.category,
                                                permitted_label_table.c.value),
                                      cascade='all, delete-orphan'),
        approvals=relationship(Approval, backref='change',
                               order_by=(approval_table.c.category,
                                         approval_table.c.value),
                               cascade='all, delete-orphan'),
        draft_approvals=relationship(Approval,
                                     primaryjoin=and_(change_table.c.key==approval_table.c.change_key,
                                                      approval_table.c.draft==True),
                                     order_by=(approval_table.c.category,
                                               approval_table.c.value))
        ))
mapper(Revision, revision_table, properties=dict(
        messages=relationship(Message, backref='revision',
                              cascade='all, delete-orphan'),
        files=relationship(File, backref='revision',
                           cascade='all, delete-orphan'),
        pending_cherry_picks=relationship(PendingCherryPick, backref='revision',
                                          cascade='all, delete-orphan'),
        ))
mapper(Message, message_table, properties=dict(
        author=relationship(Account)))
mapper(File, file_table, properties=dict(
       comments=relationship(Comment, backref='file',
                             order_by=(comment_table.c.line,
                                       comment_table.c.created),
                             cascade='all, delete-orphan'),
       draft_comments=relationship(Comment,
                                   primaryjoin=and_(file_table.c.key==comment_table.c.file_key,
                                                    comment_table.c.draft==True),
                                   order_by=(comment_table.c.line,
                                             comment_table.c.created)),
       ))

mapper(Comment, comment_table, properties=dict(
        author=relationship(Account)))
mapper(Label, label_table)
mapper(PermittedLabel, permitted_label_table)
mapper(Approval, approval_table, properties=dict(
        reviewer=relationship(Account)))
mapper(PendingCherryPick, pending_cherry_pick_table)
mapper(SyncQuery, sync_query_table)

def match(expr, item):
    if item is None:
        return False
    return re.match(expr, item) is not None

@sqlalchemy.event.listens_for(sqlalchemy.engine.Engine, "connect")
def add_sqlite_match(dbapi_connection, connection_record):
    dbapi_connection.create_function("matches", 2, match)

class Database(object):
    def __init__(self, app, dburi, search):
        self.log = logging.getLogger('gertty.db')
        self.dburi = dburi
        self.search = search
        self.engine = create_engine(self.dburi)
        #metadata.create_all(self.engine)
        self.migrate(app)
        # If we want the objects returned from query() to be usable
        # outside of the session, we need to expunge them from the session,
        # and since the DatabaseSession always calls commit() on the session
        # when the context manager exits, we need to inform the session to
        # expire objects when it does so.
        self.session_factory = sessionmaker(bind=self.engine,
                                            expire_on_commit=False,
                                            autoflush=False)
        self.session = scoped_session(self.session_factory)
        self.lock = threading.Lock()

    def getSession(self):
        return DatabaseSession(self)

    def migrate(self, app):
        conn = self.engine.connect()
        context = alembic.migration.MigrationContext.configure(conn)
        current_rev = context.get_current_revision()
        self.log.debug('Current migration revision: %s' % current_rev)

        has_table = self.engine.dialect.has_table(conn, "project")

        config = alembic.config.Config()
        config.set_main_option("script_location", "gertty:alembic")
        config.set_main_option("sqlalchemy.url", self.dburi)
        config.gertty_app = app

        if current_rev is None and has_table:
            self.log.debug('Stamping database as initial revision')
            alembic.command.stamp(config, "44402069e137")
        alembic.command.upgrade(config, 'head')

class DatabaseSession(object):
    def __init__(self, database):
        self.database = database
        self.session = database.session
        self.search = database.search

    def __enter__(self):
        self.database.lock.acquire()
        self.start = time.time()
        return self

    def __exit__(self, etype, value, tb):
        if etype:
            self.session().rollback()
        else:
            self.session().commit()
        self.session().close()
        self.session = None
        end = time.time()
        self.database.log.debug("Database lock held %s seconds" % (end-self.start,))
        self.database.lock.release()

    def abort(self):
        self.session().rollback()

    def commit(self):
        self.session().commit()

    def delete(self, obj):
        self.session().delete(obj)

    def vacuum(self):
        self.session().execute("VACUUM")

    def getProjects(self, subscribed=False, unreviewed=False):
        """Retrieve projects.

        :param subscribed: If True limit to only subscribed projects.
        :param unreviewed: If True limit to only projects with unreviewed
            changes.
        """
        query = self.session().query(Project)
        if subscribed:
            query = query.filter_by(subscribed=subscribed)
            if unreviewed:
                query = query.filter(exists().where(Project.unreviewed_changes))
        return query.order_by(Project.name).all()

    def getProject(self, key):
        try:
            return self.session().query(Project).filter_by(key=key).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getProjectByName(self, name):
        try:
            return self.session().query(Project).filter_by(name=name).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getSyncQueryByName(self, name):
        try:
            return self.session().query(SyncQuery).filter_by(name=name).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return self.createSyncQuery(name)

    def getChange(self, key):
        try:
            return self.session().query(Change).filter_by(key=key).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getChangeByID(self, id):
        try:
            return self.session().query(Change).filter_by(id=id).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getChangeIDs(self, ids):
        # Returns a set of IDs that exist in the local database matching
        # the set of supplied IDs. This is used when sync'ing the changesets
        # locally with the remote changes.
        if not ids:
            return set([])
        return set([r[0] for r in self.session().query(Change.id).filter(Change.id.in_(ids)).all()])

    def getChangeByChangeID(self, change_id):
        try:
            return self.session().query(Change).filter_by(change_id=change_id).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getChangeByNumber(self, number):
        try:
            return self.session().query(Change).filter_by(number=number).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getPendingCherryPick(self, key):
        try:
            return self.session().query(PendingCherryPick).filter_by(key=key).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getChanges(self, query, unreviewed=False, sort_by='number'):
        self.database.log.debug("Search query: %s" % query)
        q = self.session().query(Change).filter(self.search.parse(query))
        if unreviewed:
            q = q.filter(change_table.c.hidden==False, change_table.c.reviewed==False)
        if sort_by == 'updated':
            q = q.order_by(change_table.c.updated)
        else:
            q = q.order_by(change_table.c.number)
        self.database.log.debug("Search SQL: %s" % q)
        try:
            return q.all()
        except sqlalchemy.orm.exc.NoResultFound:
            return []

    def getRevision(self, key):
        try:
            return self.session().query(Revision).filter_by(key=key).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getRevisionByCommit(self, commit):
        try:
            return self.session().query(Revision).filter_by(commit=commit).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getRevisionsByParent(self, parent):
        if isinstance(parent, basestring):
            parent = (parent,)
        try:
            return self.session().query(Revision).filter(Revision.parent.in_(parent)).all()
        except sqlalchemy.orm.exc.NoResultFound:
            return []

    def getRevisionByNumber(self, change, number):
        try:
            return self.session().query(Revision).filter_by(change_key=change.key, number=number).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getFile(self, key):
        try:
            return self.session().query(File).filter_by(key=key).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getComment(self, key):
        try:
            return self.session().query(Comment).filter_by(key=key).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getCommentByID(self, id):
        try:
            return self.session().query(Comment).filter_by(id=id).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getMessage(self, key):
        try:
            return self.session().query(Message).filter_by(key=key).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getMessageByID(self, id):
        try:
            return self.session().query(Message).filter_by(id=id).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getHeld(self):
        return self.session().query(Change).filter_by(held=True).all()

    def getPendingMessages(self):
        return self.session().query(Message).filter_by(pending=True).all()

    def getPendingTopics(self):
        return self.session().query(Change).filter_by(pending_topic=True).all()

    def getPendingRebases(self):
        return self.session().query(Change).filter_by(pending_rebase=True).all()

    def getPendingStarred(self):
        return self.session().query(Change).filter_by(pending_starred=True).all()

    def getPendingStatusChanges(self):
        return self.session().query(Change).filter_by(pending_status=True).all()

    def getPendingCherryPicks(self):
        return self.session().query(PendingCherryPick).all()

    def getPendingCommitMessages(self):
        return self.session().query(Revision).filter_by(pending_message=True).all()

    def getAccountByID(self, id, name=None, username=None, email=None):
        try:
            account = self.session().query(Account).filter_by(id=id).one()
        except sqlalchemy.orm.exc.NoResultFound:
            account = self.createAccount(id)
        if name is not None and account.name != name:
            account.name = name
        if username is not None and account.username != username:
            account.username = username
        if email is not None and account.email != email:
            account.email = email
        return account

    def getAccountByUsername(self, username):
        try:
            return self.session().query(Account).filter_by(username=username).one()
        except sqlalchemy.orm.exc.NoResultFound:
            return None

    def getSystemAccount(self):
        return self.getAccountByID(0, 'Gerrit Code Review')

    def createProject(self, *args, **kw):
        o = Project(*args, **kw)
        self.session().add(o)
        self.session().flush()
        return o

    def createAccount(self, *args, **kw):
        a = Account(*args, **kw)
        self.session().add(a)
        self.session().flush()
        return a

    def createSyncQuery(self, *args, **kw):
        o = SyncQuery(*args, **kw)
        self.session().add(o)
        self.session().flush()
        return o
