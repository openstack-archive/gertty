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

import time
import logging
import threading

import alembic
import alembic.config
import sqlalchemy
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Boolean, DateTime, Text, select, func
from sqlalchemy.schema import ForeignKey
from sqlalchemy.orm import mapper, sessionmaker, relationship, column_property, scoped_session
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
    )
revision_table = Table(
    'revision', metadata,
    Column('key', Integer, primary_key=True),
    Column('change_key', Integer, ForeignKey("change.key"), index=True),
    Column('number', Integer, index=True, nullable=False),
    Column('message', Text, nullable=False),
    Column('commit', String(255), nullable=False),
    Column('parent', String(255), nullable=False),
    Column('fetch_auth', Boolean, nullable=False),
    Column('fetch_ref', String(255), nullable=False),
    )
message_table = Table(
    'message', metadata,
    Column('key', Integer, primary_key=True),
    Column('revision_key', Integer, ForeignKey("revision.key"), index=True),
    Column('account_key', Integer, ForeignKey("account.key"), index=True),
    Column('id', String(255), index=True), #, unique=True, nullable=False),
    Column('created', DateTime, index=True, nullable=False),
    Column('message', Text, nullable=False),
    Column('pending', Boolean, index=True, nullable=False),
    )
comment_table = Table(
    'comment', metadata,
    Column('key', Integer, primary_key=True),
    Column('revision_key', Integer, ForeignKey("revision.key"), index=True),
    Column('account_key', Integer, ForeignKey("account.key"), index=True),
    Column('id', String(255), index=True), #, unique=True, nullable=False),
    Column('in_reply_to', String(255)),
    Column('created', DateTime, index=True, nullable=False),
    Column('file', Text, nullable=False),
    Column('parent', Boolean, nullable=False),
    Column('line', Integer),
    Column('message', Text, nullable=False),
    Column('pending', Boolean, index=True, nullable=False),
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
    Column('pending', Boolean, index=True, nullable=False),
    )
account_table = Table(
    'account', metadata,
    Column('key', Integer, primary_key=True),
    Column('id', Integer, index=True, unique=True, nullable=False),
    Column('name', String(255), index=True),
    Column('username', String(255), index=True),
    Column('email', String(255), index=True),
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

class Change(object):
    def __init__(self, project, id, owner, number, branch,
                 change_id, subject, created, updated, status,
                 topic=False, hidden=False, reviewed=False):
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

    def getCategories(self):
        categories = []
        for label in self.labels:
            if label.category in categories:
                continue
            categories.append(label.category)
        return categories

    def getMaxForCategory(self, category):
        if not hasattr(self, '_approval_cache'):
            self._updateApprovalCache()
        return self._approval_cache.get(category, 0)

    def _updateApprovalCache(self):
        cat_min = {}
        cat_max = {}
        cat_value = {}
        for approval in self.approvals:
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

class Revision(object):
    def __init__(self, change, number, message, commit, parent, fetch_auth, fetch_ref):
        self.change_key = change.key
        self.number = number
        self.message = message
        self.commit = commit
        self.parent = parent
        self.fetch_auth = fetch_auth
        self.fetch_ref = fetch_ref

    def createMessage(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        m = Message(*args, **kw)
        self.messages.append(m)
        session.add(m)
        session.flush()
        return m

    def createComment(self, *args, **kw):
        session = Session.object_session(self)
        args = [self] + list(args)
        c = Comment(*args, **kw)
        self.comments.append(c)
        session.add(c)
        session.flush()
        return c

class Message(object):
    def __init__(self, revision, id, author, created, message, pending=False):
        self.revision_key = revision.key
        self.account_key = author.key
        self.id = id
        self.created = created
        self.message = message
        self.pending = pending

class Comment(object):
    def __init__(self, revision, id, author, in_reply_to, created, file, parent, line, message, pending=False):
        self.revision_key = revision.key
        self.account_key = author.key
        self.id = id
        self.in_reply_to = in_reply_to
        self.created = created
        self.file = file
        self.parent = parent
        self.line = line
        self.message = message
        self.pending = pending

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
    def __init__(self, change, reviewer, category, value, pending=False):
        self.change_key = change.key
        self.account_key = reviewer.key
        self.category = category
        self.value = value
        self.pending = pending

mapper(Account, account_table)
mapper(Project, project_table, properties=dict(
        changes=relationship(Change, backref='project',
                             order_by=change_table.c.number),
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
mapper(Change, change_table, properties=dict(
        owner=relationship(Account),
        revisions=relationship(Revision, backref='change',
                               order_by=revision_table.c.number),
        messages=relationship(Message,
                              secondary=revision_table,
                              order_by=message_table.c.created),
        labels=relationship(Label, backref='change', order_by=(label_table.c.category,
                                                               label_table.c.value)),
        permitted_labels=relationship(PermittedLabel, backref='change',
                                      order_by=(permitted_label_table.c.category,
                                                permitted_label_table.c.value)),
        approvals=relationship(Approval, backref='change', order_by=(approval_table.c.category,
                                                                     approval_table.c.value)),
        pending_approvals=relationship(Approval,
                                       primaryjoin=and_(change_table.c.key==approval_table.c.change_key,
                                                        approval_table.c.pending==True),
                                       order_by=(approval_table.c.category,
                                                 approval_table.c.value))
        ))
mapper(Revision, revision_table, properties=dict(
        messages=relationship(Message, backref='revision'),
        comments=relationship(Comment, backref='revision',
                              order_by=(comment_table.c.line,
                                        comment_table.c.created)),
        pending_comments=relationship(Comment,
                                      primaryjoin=and_(revision_table.c.key==comment_table.c.revision_key,
                                                       comment_table.c.pending==True),
                                      order_by=(comment_table.c.line,
                                                comment_table.c.created)),
        ))
mapper(Message, message_table, properties=dict(
        author=relationship(Account)))
mapper(Comment, comment_table, properties=dict(
        author=relationship(Account)))
mapper(Label, label_table)
mapper(PermittedLabel, permitted_label_table)
mapper(Approval, approval_table, properties=dict(
        reviewer=relationship(Account)))

class Database(object):
    def __init__(self, app):
        self.log = logging.getLogger('gertty.db')
        self.app = app
        self.engine = create_engine(self.app.config.dburi)
        #metadata.create_all(self.engine)
        self.migrate()
        self.session_factory = sessionmaker(bind=self.engine)
        self.session = scoped_session(self.session_factory)
        self.lock = threading.Lock()

    def getSession(self):
        return DatabaseSession(self)

    def migrate(self):
        conn = self.engine.connect()
        context = alembic.migration.MigrationContext.configure(conn)
        current_rev = context.get_current_revision()
        self.log.debug('Current migration revision: %s' % current_rev)

        has_table = self.engine.dialect.has_table(conn, "project")

        config = alembic.config.Config()
        config.set_main_option("script_location", "gertty:alembic")
        config.set_main_option("sqlalchemy.url", self.app.config.dburi)

        if current_rev is None and has_table:
            self.log.debug('Stamping database as initial revision')
            alembic.command.stamp(config, "44402069e137")
        alembic.command.upgrade(config, 'head')

class DatabaseSession(object):
    def __init__(self, database):
        self.database = database
        self.session = database.session
        self.search = database.app.search

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

    def getChanges(self, query, unreviewed=False):
        self.database.log.debug("Search query: %s" % query)
        q = self.session().query(Change).filter(self.search.parse(query))
        if unreviewed:
            q = q.filter(change_table.c.hidden==False, change_table.c.reviewed==False)
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
        try:
            return self.session().query(Revision).filter_by(parent=parent).all()
        except sqlalchemy.orm.exc.NoResultFound:
            return []

    def getRevisionByNumber(self, change, number):
        try:
            return self.session().query(Revision).filter_by(change_key=change.key, number=number).one()
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

    def getPendingMessages(self):
        return self.session().query(Message).filter_by(pending=True).all()

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
