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

import collections
import errno
import logging
import math
import os
import re
import threading
import urllib
import urlparse
import json
import time
import Queue
import datetime

import dateutil.parser
try:
    import ordereddict
except:
    pass
import requests
import requests.utils

import gertty.version
from gertty import gitrepo

HIGH_PRIORITY=0
NORMAL_PRIORITY=1
LOW_PRIORITY=2

TIMEOUT=30

CLOSED_STATUSES = ['MERGED', 'ABANDONED']


class MultiQueue(object):
    def __init__(self, priorities):
        try:
            self.queues = collections.OrderedDict()
        except AttributeError:
            self.queues = ordereddict.OrderedDict()
        for key in priorities:
            self.queues[key] = collections.deque()
        self.condition = threading.Condition()

    def qsize(self):
        count = 0
        for queue in self.queues.values():
            count += len(queue)
        return count

    def put(self, item, priority):
        added = False
        self.condition.acquire()
        try:
            if item not in self.queues[priority]:
                self.queues[priority].append(item)
                added = True
            self.condition.notify()
        finally:
            self.condition.release()
        return added

    def get(self):
        self.condition.acquire()
        try:
            while True:
                for queue in self.queues.values():
                    try:
                        ret = queue.popleft()
                        return ret
                    except IndexError:
                        pass
                self.condition.wait()
        finally:
            self.condition.release()

    def find(self, klass, priority):
        results = []
        self.condition.acquire()
        try:
            for item in self.queues[priority]:
                if isinstance(item, klass):
                    results.append(item)
        finally:
            self.condition.release()
        return results


class UpdateEvent(object):
    def updateRelatedChanges(self, session, change):
        related_change_keys = set()
        related_change_keys.add(change.key)
        for revision in change.revisions:
            parent = session.getRevisionByCommit(revision.parent)
            if parent:
                related_change_keys.add(parent.change.key)
            for child in session.getRevisionsByParent(revision.commit):
                related_change_keys.add(child.change.key)
        self.related_change_keys = related_change_keys

class ProjectAddedEvent(UpdateEvent):
    def __repr__(self):
        return '<ProjectAddedEvent project_key:%s>' % (
            self.project_key,)

    def __init__(self, project):
        self.project_key = project.key

class ChangeAddedEvent(UpdateEvent):
    def __repr__(self):
        return '<ChangeAddedEvent project_key:%s change_key:%s>' % (
            self.project_key, self.change_key)

    def __init__(self, change):
        self.project_key = change.project.key
        self.change_key = change.key
        self.related_change_keys = set()
        self.review_flag_changed = True
        self.status_changed = True
        self.held_changed = False

class ChangeUpdatedEvent(UpdateEvent):
    def __repr__(self):
        return '<ChangeUpdatedEvent project_key:%s change_key:%s review_flag_changed:%s status_changed:%s>' % (
            self.project_key, self.change_key, self.review_flag_changed, self.status_changed)

    def __init__(self, change):
        self.project_key = change.project.key
        self.change_key = change.key
        self.related_change_keys = set()
        self.review_flag_changed = False
        self.status_changed = False
        self.held_changed = False

class Task(object):
    def __init__(self, priority=NORMAL_PRIORITY):
        self.log = logging.getLogger('gertty.sync')
        self.priority = priority
        self.succeeded = None
        self.event = threading.Event()
        self.tasks = []
        self.results = []

    def complete(self, success):
        self.succeeded = success
        self.event.set()

    def wait(self, timeout=None):
        self.event.wait(timeout)
        return self.succeeded

    def __eq__(self, other):
        raise NotImplementedError()

class SyncOwnAccountTask(Task):
    def __repr__(self):
        return '<SyncOwnAccountTask>'

    def __eq__(self, other):
        if other.__class__ == self.__class__:
            return True
        return False

    def run(self, sync):
        app = sync.app
        remote = sync.get('accounts/self')
        sync.account_id = remote['_account_id']
        with app.db.getSession() as session:
            session.getAccountByID(remote['_account_id'],
                                   remote.get('name'),
                                   remote.get('username'),
                                   remote.get('email'))

class GetVersionTask(Task):
    def __repr__(self):
        return '<GetVersionTask>'

    def __eq__(self, other):
        if other.__class__ == self.__class__:
            return True
        return False

    def run(self, sync):
        version = sync.get('config/server/version')
        sync.setRemoteVersion(version)

class SyncProjectListTask(Task):
    def __repr__(self):
        return '<SyncProjectListTask>'

    def __eq__(self, other):
        if other.__class__ == self.__class__:
            return True
        return False

    def run(self, sync):
        app = sync.app
        remote = sync.get('projects/?d')
        remote_keys = set(remote.keys())
        with app.db.getSession() as session:
            local = {}
            for p in session.getProjects():
                local[p.name] = p
            local_keys = set(local.keys())

            for name in local_keys-remote_keys:
                session.delete(local[name])

            for name in remote_keys-local_keys:
                p = remote[name]
                project = session.createProject(name,
                                                description=p.get('description', ''))
                self.log.info("Created project %s", project.name)
                self.results.append(ProjectAddedEvent(project))

class SyncSubscribedProjectBranchesTask(Task):
    def __repr__(self):
        return '<SyncSubscribedProjectBranchesTask>'

    def __eq__(self, other):
        if other.__class__ == self.__class__:
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            projects = session.getProjects(subscribed=True)
        for p in projects:
            sync.submitTask(SyncProjectBranchesTask(p.name, self.priority))

class SyncProjectBranchesTask(Task):
    branch_re = re.compile(r'refs/heads/(.*)')

    def __init__(self, project_name, priority=NORMAL_PRIORITY):
        super(SyncProjectBranchesTask, self).__init__(priority)
        self.project_name = project_name

    def __repr__(self):
        return '<SyncProjectBranchesTask %s>' % (self.project_name,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.project_name == self.project_name):
            return True
        return False

    def run(self, sync):
        app = sync.app
        remote = sync.get('projects/%s/branches/' % urllib.quote_plus(self.project_name))
        remote_branches = set()
        for x in remote:
            m = self.branch_re.match(x['ref'])
            if m:
                remote_branches.add(m.group(1))
        with app.db.getSession() as session:
            local = {}
            project = session.getProjectByName(self.project_name)
            for branch in project.branches:
                local[branch.name] = branch
            local_branches = set(local.keys())

            for name in local_branches-remote_branches:
                session.delete(local[name])
                self.log.info("Deleted branch %s from project %s in local DB.", name, project.name)

            for name in remote_branches-local_branches:
                project.createBranch(name)
                self.log.info("Added branch %s to project %s in local DB.", name, project.name)

class SyncSubscribedProjectsTask(Task):
    def __repr__(self):
        return '<SyncSubscribedProjectsTask>'

    def __eq__(self, other):
        if (other.__class__ == self.__class__):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            keys = [p.key for p in session.getProjects(subscribed=True)]
        for i in range(0, len(keys), 10):
            t = SyncProjectTask(keys[i:i+10], self.priority)
            self.tasks.append(t)
            sync.submitTask(t)
        t = SyncQueriedChangesTask('owner', 'is:owner', self.priority)
        self.tasks.append(t)
        sync.submitTask(t)
        t = SyncQueriedChangesTask('starred', 'is:starred', self.priority)
        self.tasks.append(t)
        sync.submitTask(t)

class SyncProjectTask(Task):
    def __init__(self, project_keys, priority=NORMAL_PRIORITY):
        super(SyncProjectTask, self).__init__(priority)
        if type(project_keys) == int:
            project_keys = [project_keys]
        self.project_keys = project_keys

    def __repr__(self):
        return '<SyncProjectTask %s>' % (self.project_keys,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.project_keys == self.project_keys):
            return True
        return False

    def run(self, sync):
        app = sync.app
        now = datetime.datetime.utcnow()
        queries = []
        with app.db.getSession() as session:
            for project_key in self.project_keys:
                project = session.getProject(project_key)
                query = 'q=project:%s' % project.name
                if project.updated:
                    # Allow 4 seconds for request time, etc.
                    query += ' -age:%ss' % (int(math.ceil((now-project.updated).total_seconds())) + 4,)
                else:
                    query += ' status:open'
                queries.append(query)
        changes = []
        sortkey = ''
        done = False
        while not done:
            query = '&'.join(queries)
            # We don't actually want to limit to 500, but that's the server-side default, and
            # if we don't specify this, we won't get a _more_changes flag.
            q = 'changes/?n=500%s&%s' % (sortkey, query)
            self.log.debug('Query: %s ' % (q,))
            responses = sync.get(q)
            if len(queries) == 1:
                responses = [responses]
            done = True
            for batch in responses:
                changes += batch
                if batch and '_more_changes' in batch[-1]:
                    sortkey = '&N=%s' % (batch[-1]['_sortkey'],)
                    done = False
        change_ids = [c['id'] for c in changes]
        with app.db.getSession() as session:
            # Winnow the list of IDs to only the ones in the local DB.
            change_ids = session.getChangeIDs(change_ids)

        for c in changes:
            # For now, just sync open changes or changes already
            # in the db optionally we could sync all changes ever
            if c['id'] in change_ids or (c['status'] not in CLOSED_STATUSES):
                sync.submitTask(SyncChangeTask(c['id'], priority=self.priority))
        for key in self.project_keys:
            sync.submitTask(SetProjectUpdatedTask(key, now, priority=self.priority))

class SetProjectUpdatedTask(Task):
    def __init__(self, project_key, updated, priority=NORMAL_PRIORITY):
        super(SetProjectUpdatedTask, self).__init__(priority)
        self.project_key = project_key
        self.updated = updated

    def __repr__(self):
        return '<SetProjectUpdatedTask %s %s>' % (self.project_key, self.updated)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.project_key == self.project_key and
            other.updated == self.updated):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            project = session.getProject(self.project_key)
            project.updated = self.updated

class SyncQueriedChangesTask(Task):
    def __init__(self, query_name, query, priority=NORMAL_PRIORITY):
        super(SyncQueriedChangesTask, self).__init__(priority)
        self.query_name = query_name
        self.query = query

    def __repr__(self):
        return '<SyncQueriedChangesTask %s>' % self.query_name

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.query_name == self.query_name and
            other.query == self.query):
            return True
        return False

    def run(self, sync):
        app = sync.app
        now = datetime.datetime.utcnow()
        with app.db.getSession() as session:
            sync_query = session.getSyncQueryByName(self.query_name)
            query = 'q=%s' % self.query
            if sync_query.updated:
                # Allow 4 seconds for request time, etc.
                query += ' -age:%ss' % (int(math.ceil((now-sync_query.updated).total_seconds())) + 4,)
            else:
                query += ' status:open'
            for project in session.getProjects(subscribed=True):
                query += ' -project:%s' % project.name
        changes = []
        sortkey = ''
        done = False
        while not done:
            # We don't actually want to limit to 500, but that's the server-side default, and
            # if we don't specify this, we won't get a _more_changes flag.
            q = 'changes/?n=500%s&%s' % (sortkey, query)
            self.log.debug('Query: %s ' % (q,))
            batch = sync.get(q)
            done = True
            if batch:
                changes += batch
                if '_more_changes' in batch[-1]:
                    sortkey = '&N=%s' % (batch[-1]['_sortkey'],)
                    done = False
        change_ids = [c['id'] for c in changes]
        with app.db.getSession() as session:
            # Winnow the list of IDs to only the ones in the local DB.
            change_ids = session.getChangeIDs(change_ids)

        for c in changes:
            # For now, just sync open changes or changes already
            # in the db optionally we could sync all changes ever
            if c['id'] in change_ids or (c['status'] not in CLOSED_STATUSES):
                sync.submitTask(SyncChangeTask(c['id'], priority=self.priority))
        sync.submitTask(SetSyncQueryUpdatedTask(self.query_name, now, priority=self.priority))

class SetSyncQueryUpdatedTask(Task):
    def __init__(self, query_name, updated, priority=NORMAL_PRIORITY):
        super(SetSyncQueryUpdatedTask, self).__init__(priority)
        self.query_name = query_name
        self.updated = updated

    def __repr__(self):
        return '<SetSyncQueryUpdatedTask %s %s>' % (self.query_name, self.updated)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.query_name == self.query_name and
            other.updated == self.updated):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            sync_query = session.getSyncQueryByName(self.query_name)
            sync_query.updated = self.updated

class SyncChangesByCommitsTask(Task):
    def __init__(self, commits, priority=NORMAL_PRIORITY):
        super(SyncChangesByCommitsTask, self).__init__(priority)
        self.commits = commits

    def __repr__(self):
        return '<SyncChangesByCommitsTask %s>' % (self.commits,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.commits == self.commits):
            return True
        return False

    def run(self, sync):
        query = ' OR '.join(['commit:%s' % x for x in self.commits])
        changes = sync.get('changes/?q=%s' % query)
        self.log.debug('Query: %s ' % (query,))
        for c in changes:
            sync.submitTask(SyncChangeTask(c['id'], priority=self.priority))
            self.log.debug("Sync change %s for its commit" % (c['id'],))

    def addCommit(self, commit):
        if commit in self.commits:
            return True
        # 100 should be under the URL length limit
        if len(self.commits) >= 100:
            return False
        self.commits.append(commit)
        return True

class SyncChangeByNumberTask(Task):
    def __init__(self, number, priority=NORMAL_PRIORITY):
        super(SyncChangeByNumberTask, self).__init__(priority)
        self.number = number

    def __repr__(self):
        return '<SyncChangeByNumberTask %s>' % (self.number,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.number == self.number):
            return True
        return False

    def run(self, sync):
        query = '%s' % self.number
        changes = sync.get('changes/?q=%s' % query)
        self.log.debug('Query: %s ' % (query,))
        for c in changes:
            task = SyncChangeTask(c['id'], priority=self.priority)
            self.tasks.append(task)
            sync.submitTask(task)
            self.log.debug("Sync change %s because it is number %s" % (c['id'], self.number))

class SyncChangeTask(Task):
    def __init__(self, change_id, force_fetch=False, priority=NORMAL_PRIORITY):
        super(SyncChangeTask, self).__init__(priority)
        self.change_id = change_id
        self.force_fetch = force_fetch

    def __repr__(self):
        return '<SyncChangeTask %s>' % (self.change_id,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.change_id == self.change_id and
            other.force_fetch == self.force_fetch):
            return True
        return False

    def run(self, sync):
        start_time = time.time()
        app = sync.app
        remote_change = sync.get('changes/%s?o=DETAILED_LABELS&o=ALL_REVISIONS&o=ALL_COMMITS&o=MESSAGES&o=DETAILED_ACCOUNTS&o=CURRENT_ACTIONS&o=ALL_FILES' % self.change_id)
        # Perform subqueries this task will need outside of the db session
        for remote_commit, remote_revision in remote_change.get('revisions', {}).items():
            remote_comments_data = sync.get('changes/%s/revisions/%s/comments' % (self.change_id, remote_commit))
            remote_revision['_gertty_remote_comments_data'] = remote_comments_data
        fetches = collections.defaultdict(list)
        parent_commits = set()
        with app.db.getSession() as session:
            change = session.getChangeByID(self.change_id)
            account = session.getAccountByID(remote_change['owner']['_account_id'],
                                             name=remote_change['owner'].get('name'),
                                             username=remote_change['owner'].get('username'),
                                             email=remote_change['owner'].get('email'))
            if not change:
                project = session.getProjectByName(remote_change['project'])
                created = dateutil.parser.parse(remote_change['created'])
                updated = dateutil.parser.parse(remote_change['updated'])
                change = project.createChange(remote_change['id'], account, remote_change['_number'],
                                              remote_change['branch'], remote_change['change_id'],
                                              remote_change['subject'], created,
                                              updated, remote_change['status'],
                                              topic=remote_change.get('topic'))
                self.log.info("Created new change %s in local DB.", change.id)
                result = ChangeAddedEvent(change)
            else:
                result = ChangeUpdatedEvent(change)
            self.results.append(result)
            change.owner = account
            if change.status != remote_change['status']:
                change.status = remote_change['status']
                result.status_changed = True
            if remote_change.get('starred'):
                change.starred = True
            else:
                change.starred = False
            change.subject = remote_change['subject']
            change.updated = dateutil.parser.parse(remote_change['updated'])
            change.topic = remote_change.get('topic')
            repo = gitrepo.get_repo(change.project.name, app.config)
            new_revision = False
            for remote_commit, remote_revision in remote_change.get('revisions', {}).items():
                revision = session.getRevisionByCommit(remote_commit)
                # TODO: handle multiple parents
                if 'anonymous http' in remote_revision['fetch']:
                    ref = remote_revision['fetch']['anonymous http']['ref']
                    url = remote_revision['fetch']['anonymous http']['url']
                    auth = False
                elif 'http' in remote_revision['fetch']:
                    auth = True
                    ref = remote_revision['fetch']['http']['ref']
                    url = list(urlparse.urlsplit(sync.app.config.url + change.project.name))
                    url[1] = '%s:%s@%s' % (
                        urllib.quote_plus(sync.app.config.username),
                        urllib.quote_plus(sync.app.config.password), url[1])
                    url = urlparse.urlunsplit(url)
                elif 'ssh' in remote_revision['fetch']:
                    ref = remote_revision['fetch']['ssh']['ref']
                    url = remote_revision['fetch']['ssh']['url']
                    auth = False
                elif 'git' in remote_revision['fetch']:
                    ref = remote_revision['fetch']['git']['ref']
                    url = remote_revision['fetch']['git']['url']
                    auth = False
                else:
                    if len(remote_revision['fetch']):
                        errMessage = "No supported fetch method found.  Server offers: %s" % (
                            ', '.join(remote_revision['fetch'].keys()))
                    else:
                        errMessage = "The server is missing the download-commands plugin."
                    raise Exception(errMessage)
                if (not revision) or self.force_fetch:
                    fetches[url].append('+%(ref)s:%(ref)s' % dict(ref=ref))
                if not revision:
                    revision = change.createRevision(remote_revision['_number'],
                                                     remote_revision['commit']['message'], remote_commit,
                                                     remote_revision['commit']['parents'][0]['commit'],
                                                     auth, ref)
                    self.log.info("Created new revision %s for change %s revision %s in local DB.",
                                  revision.key, self.change_id, remote_revision['_number'])
                    new_revision = True
                revision.message = remote_revision['commit']['message']
                actions = remote_revision.get('actions', {})
                revision.can_submit = 'submit' in actions
                # TODO: handle multiple parents
                if revision.parent not in parent_commits:
                    parent_revision = session.getRevisionByCommit(revision.parent)
                    if not parent_revision and change.status not in CLOSED_STATUSES:
                        sync._syncChangeByCommit(revision.parent, self.priority)
                        self.log.debug("Change %s revision %s needs parent commit %s synced" %
                                       (change.id, remote_revision['_number'], revision.parent))
                    parent_commits.add(revision.parent)
                result.updateRelatedChanges(session, change)

                f = revision.getFile('/COMMIT_MSG')
                if f is None:
                    f = revision.createFile('/COMMIT_MSG', None,
                                            None, None, None)
                for remote_path, remote_file in remote_revision['files'].items():
                    f = revision.getFile(remote_path)
                    if f is None:
                        if remote_file.get('binary'):
                            inserted = deleted = None
                        else:
                            inserted = remote_file.get('lines_inserted', 0)
                            deleted = remote_file.get('lines_deleted', 0)
                        f = revision.createFile(remote_path, remote_file.get('status', 'M'),
                                                remote_file.get('old_path'),
                                                inserted, deleted)

                remote_comments_data = remote_revision['_gertty_remote_comments_data']
                for remote_file, remote_comments in remote_comments_data.items():
                    for remote_comment in remote_comments:
                        account = session.getAccountByID(remote_comment['author']['_account_id'],
                                                         name=remote_comment['author'].get('name'),
                                                         username=remote_comment['author'].get('username'),
                                                         email=remote_comment['author'].get('email'))
                        comment = session.getCommentByID(remote_comment['id'])
                        if not comment:
                            # Normalize updated -> created
                            created = dateutil.parser.parse(remote_comment['updated'])
                            parent = False
                            if remote_comment.get('side', '') == 'PARENT':
                                parent = True
                            fileobj = revision.getFile(remote_file)
                            if fileobj is None:
                                fileobj = revision.createFile(remote_file, 'M')
                            comment = fileobj.createComment(remote_comment['id'], account,
                                                            remote_comment.get('in_reply_to'),
                                                            created,
                                                            parent, remote_comment.get('line'),
                                                            remote_comment['message'])
                            self.log.info("Created new comment %s for revision %s in local DB.",
                                          comment.key, revision.key)
                        else:
                            if comment.author != account:
                                comment.author = account
            new_message = False
            for remote_message in remote_change.get('messages', []):
                if 'author' in remote_message:
                    account = session.getAccountByID(remote_message['author']['_account_id'],
                                                     name=remote_message['author'].get('name'),
                                                     username=remote_message['author'].get('username'),
                                                     email=remote_message['author'].get('email'))
                    if account.username != app.config.username:
                        new_message = True
                else:
                    account = session.getSystemAccount()
                message = session.getMessageByID(remote_message['id'])
                if not message:
                    revision = session.getRevisionByNumber(change, remote_message.get('_revision_number', 1))
                    if revision:
                        # Normalize date -> created
                        created = dateutil.parser.parse(remote_message['date'])
                        message = revision.createMessage(remote_message['id'], account, created,
                                                     remote_message['message'])
                        self.log.info("Created new review message %s for revision %s in local DB.", message.key, revision.key)
                    else:
                        self.log.info("Unable to create new review message for revision %s because it is not in local DB (draft?).", remote_message.get('_revision_number'))
                else:
                    if message.author != account:
                        message.author = account
            remote_approval_entries = {}
            remote_label_entries = {}
            user_voted = False
            for remote_label_name, remote_label_dict in remote_change.get('labels', {}).items():
                for remote_approval in remote_label_dict.get('all', []):
                    if remote_approval.get('value') is None:
                        continue
                    remote_approval['category'] = remote_label_name
                    key = '%s~%s' % (remote_approval['category'], remote_approval['_account_id'])
                    remote_approval_entries[key] = remote_approval
                    if remote_approval['_account_id'] == sync.account_id and int(remote_approval['value']) != 0:
                        user_voted = True
                for key, value in remote_label_dict.get('values', {}).items():
                    # +1: "LGTM"
                    label = dict(value=key,
                                 description=value,
                                 category=remote_label_name)
                    key = '%s~%s~%s' % (label['category'], label['value'], label['description'])
                    remote_label_entries[key] = label
            remote_approval_keys = set(remote_approval_entries.keys())
            remote_label_keys = set(remote_label_entries.keys())
            local_approvals = {}
            local_labels = {}
            user_votes = {}
            for approval in change.approvals:
                if approval.draft and not new_revision:
                    # If we have a new revision, we need to delete
                    # draft local approvals because they can no longer
                    # be uploaded.  Otherwise, keep them because we
                    # may be about to upload a review.  Ignoring an
                    # approval here means it will not be deleted.
                    # Also keep track of these approvals so we can
                    # determine whether we should hold the change
                    # later.
                    user_votes[approval.category] = approval.value
                    # Count draft votes as having voted for the
                    # purposes of deciding whether to clear the
                    # reviewed flag later.
                    user_voted = True
                    continue
                key = '%s~%s' % (approval.category, approval.reviewer.id)
                if key in local_approvals:
                    # Delete duplicate approvals.
                    session.delete(approval)
                else:
                    local_approvals[key] = approval
            local_approval_keys = set(local_approvals.keys())
            for label in change.labels:
                key = '%s~%s~%s' % (label.category, label.value, label.description)
                local_labels[key] = label
            local_label_keys = set(local_labels.keys())

            for key in local_approval_keys-remote_approval_keys:
                session.delete(local_approvals[key])

            for key in local_label_keys-remote_label_keys:
                session.delete(local_labels[key])

            for key in remote_approval_keys-local_approval_keys:
                remote_approval = remote_approval_entries[key]
                account = session.getAccountByID(remote_approval['_account_id'],
                                                 name=remote_approval.get('name'),
                                                 username=remote_approval.get('username'),
                                                 email=remote_approval.get('email'))
                change.createApproval(account,
                                      remote_approval['category'],
                                      remote_approval['value'])
                self.log.info("Created approval for change %s in local DB.", change.id)
                user_value = user_votes.get(remote_approval['category'], 0)
                if user_value > 0 and remote_approval['value'] < 0:
                    # Someone left a negative vote after the local
                    # user created a draft positive vote.  Hold the
                    # change so that it doesn't look like the local
                    # user is ignoring negative feedback.
                    if not change.held:
                        change.held = True
                        result.held_changed = True
                        self.log.info("Setting change %s to held due to negative review after positive", change.id)

            for key in remote_label_keys-local_label_keys:
                remote_label = remote_label_entries[key]
                change.createLabel(remote_label['category'],
                                   remote_label['value'],
                                   remote_label['description'])

            for key in remote_approval_keys.intersection(local_approval_keys):
                local_approval = local_approvals[key]
                remote_approval = remote_approval_entries[key]
                local_approval.value = remote_approval['value']
                # For the side effect of updating account info:
                account = session.getAccountByID(remote_approval['_account_id'],
                                                 name=remote_approval.get('name'),
                                                 username=remote_approval.get('username'),
                                                 email=remote_approval.get('email'))

            remote_permitted_entries = {}
            for remote_label_name, remote_label_values in remote_change.get('permitted_labels', {}).items():
                for remote_label_value in remote_label_values:
                    remote_label = dict(category=remote_label_name,
                                        value=remote_label_value)
                    key = '%s~%s' % (remote_label['category'], remote_label['value'])
                    remote_permitted_entries[key] = remote_label
            remote_permitted_keys = set(remote_permitted_entries.keys())
            local_permitted = {}
            for permitted in change.permitted_labels:
                key = '%s~%s' % (permitted.category, permitted.value)
                local_permitted[key] = permitted
            local_permitted_keys = set(local_permitted.keys())

            for key in local_permitted_keys-remote_permitted_keys:
                session.delete(local_permitted[key])

            for key in remote_permitted_keys-local_permitted_keys:
                remote_permitted = remote_permitted_entries[key]
                change.createPermittedLabel(remote_permitted['category'],
                                            remote_permitted['value'])

            if not user_voted:
                # Only consider changing the reviewed state if we don't have a vote
                if new_revision or new_message:
                    if change.reviewed:
                        change.reviewed = False
                        result.review_flag_changed = True
        for url, refs in fetches.items():
            self.log.debug("Fetching from %s with refs %s", url, refs)
            try:
                repo.fetch(url, refs)
            except Exception:
                # Backwards compat with GitPython before the multi-ref fetch
                # patch.
                # (https://github.com/gitpython-developers/GitPython/pull/170)
                for ref in refs:
                    self.log.debug("git fetch %s %s" % (url, ref))
                    repo.fetch(url, ref)
        end_time = time.time()
        total_time = end_time - start_time
        self.log.info("Synced change %s in %0.5f seconds.", self.change_id, total_time)

class CheckReposTask(Task):
    # on startup, check all projects
    #   for any subscribed project withot a local repo or if
    #   --fetch-missing-refs is supplied, check all local changes for
    #   missing refs, and sync the associated changes
    def __repr__(self):
        return '<CheckReposTask>'

    def __eq__(self, other):
        if (other.__class__ == self.__class__):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            projects = session.getProjects(subscribed=True)
        for project in projects:
            try:
                missing = False
                try:
                    repo = gitrepo.get_repo(project.name, app.config)
                except gitrepo.GitCloneError:
                    missing = True
                if missing or app.fetch_missing_refs:
                    sync.submitTask(CheckRevisionsTask(project.key,
                                                       priority=LOW_PRIORITY))
            except Exception:
                self.log.exception("Exception checking repo %s" %
                                   (project.name,))

class CheckRevisionsTask(Task):
    def __init__(self, project_key, priority=NORMAL_PRIORITY):
        super(CheckRevisionsTask, self).__init__(priority)
        self.project_key = project_key

    def __repr__(self):
        return '<CheckRevisionsTask %s>' % (self.project_key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.project_key == self.project_key):
            return True
        return False

    def run(self, sync):
        app = sync.app
        to_sync = set()
        with app.db.getSession() as session:
            project = session.getProject(self.project_key)
            repo = None
            try:
                repo = gitrepo.get_repo(project.name, app.config)
            except gitrepo.GitCloneError:
                pass
            for change in project.open_changes:
                if repo:
                    for revision in change.revisions:
                        if not (repo.hasCommit(revision.parent) and
                                repo.hasCommit(revision.commit)):
                            to_sync.add(change.id)
                else:
                    to_sync.add(change.id)
        for change_id in to_sync:
            sync.submitTask(SyncChangeTask(change_id, priority=self.priority))

class UploadReviewsTask(Task):
    def __repr__(self):
        return '<UploadReviewsTask>'

    def __eq__(self, other):
        if (other.__class__ == self.__class__):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            for c in session.getPendingTopics():
                sync.submitTask(SetTopicTask(c.key, self.priority))
            for c in session.getPendingRebases():
                sync.submitTask(RebaseChangeTask(c.key, self.priority))
            for c in session.getPendingStatusChanges():
                sync.submitTask(ChangeStatusTask(c.key, self.priority))
            for c in session.getPendingStarred():
                sync.submitTask(ChangeStarredTask(c.key, self.priority))
            for c in session.getPendingCherryPicks():
                sync.submitTask(SendCherryPickTask(c.key, self.priority))
            for r in session.getPendingCommitMessages():
                sync.submitTask(ChangeCommitMessageTask(r.key, self.priority))
            for m in session.getPendingMessages():
                sync.submitTask(UploadReviewTask(m.key, self.priority))

class SetTopicTask(Task):
    def __init__(self, change_key, priority=NORMAL_PRIORITY):
        super(SetTopicTask, self).__init__(priority)
        self.change_key = change_key

    def __repr__(self):
        return '<SetTopicTask %s>' % (self.change_key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.change_key == self.change_key):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            change = session.getChange(self.change_key)
            data = dict(topic=change.topic)
            change.pending_topic = False
            # Inside db session for rollback
            sync.put('changes/%s/topic' % (change.id,),
                     data)
            sync.submitTask(SyncChangeTask(change.id, priority=self.priority))

class RebaseChangeTask(Task):
    def __init__(self, change_key, priority=NORMAL_PRIORITY):
        super(RebaseChangeTask, self).__init__(priority)
        self.change_key = change_key

    def __repr__(self):
        return '<RebaseChangeTask %s>' % (self.change_key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.change_key == self.change_key):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            change = session.getChange(self.change_key)
            change.pending_rebase = False
            # Inside db session for rollback
            sync.post('changes/%s/rebase' % (change.id,), {})
            sync.submitTask(SyncChangeTask(change.id, priority=self.priority))

class ChangeStarredTask(Task):
    def __init__(self, change_key, priority=NORMAL_PRIORITY):
        super(ChangeStarredTask, self).__init__(priority)
        self.change_key = change_key

    def __repr__(self):
        return '<ChangeStarredTask %s>' % (self.change_key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.change_key == self.change_key):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            change = session.getChange(self.change_key)
            if change.starred:
                sync.put('accounts/self/starred.changes/%s' % (change.id,),
                         data={})
            else:
                sync.delete('accounts/self/starred.changes/%s' % (change.id,),
                            data={})
            change.pending_starred = False
            sync.submitTask(SyncChangeTask(change.id, priority=self.priority))

class ChangeStatusTask(Task):
    def __init__(self, change_key, priority=NORMAL_PRIORITY):
        super(ChangeStatusTask, self).__init__(priority)
        self.change_key = change_key

    def __repr__(self):
        return '<ChangeStatusTask %s>' % (self.change_key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.change_key == self.change_key):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            change = session.getChange(self.change_key)
            if change.pending_status_message:
                data = dict(message=change.pending_status_message)
            else:
                data = {}
            change.pending_status = False
            change.pending_status_message = None
            # Inside db session for rollback
            if change.status == 'ABANDONED':
                sync.post('changes/%s/abandon' % (change.id,),
                          data)
            elif change.status == 'NEW':
                sync.post('changes/%s/restore' % (change.id,),
                          data)
            elif change.status == 'SUBMITTED':
                sync.post('changes/%s/submit' % (change.id,), {})
            sync.submitTask(SyncChangeTask(change.id, priority=self.priority))

class SendCherryPickTask(Task):
    def __init__(self, cp_key, priority=NORMAL_PRIORITY):
        super(SendCherryPickTask, self).__init__(priority)
        self.cp_key = cp_key

    def __repr__(self):
        return '<SendCherryPickTask %s>' % (self.cp_key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.cp_key == self.cp_key):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            cp = session.getPendingCherryPick(self.cp_key)
            data = dict(message=cp.message,
                        destination=cp.branch)
            session.delete(cp)
            # Inside db session for rollback
            ret = sync.post('changes/%s/revisions/%s/cherrypick' %
                            (cp.revision.change.id, cp.revision.commit),
                            data)
        if ret and 'id' in ret:
            sync.submitTask(SyncChangeTask(ret['id'], priority=self.priority))

class ChangeCommitMessageTask(Task):
    def __init__(self, revision_key, priority=NORMAL_PRIORITY):
        super(ChangeCommitMessageTask, self).__init__(priority)
        self.revision_key = revision_key

    def __repr__(self):
        return '<ChangeCommitMessageTask %s>' % (self.revision_key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.revision_key == self.revision_key):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            revision = session.getRevision(self.revision_key)
            revision.pending_message = False
            data = dict(message=revision.message)
            # Inside db session for rollback
            if sync.version < (2,11,0):
                sync.post('changes/%s/revisions/%s/message' %
                          (revision.change.id, revision.commit),
                          data)
            else:
                edit = sync.get('changes/%s/edit' % revision.change.id)
                if edit is not None:
                    raise Exception("Edit already in progress on change %s" %
                                    (revision.change.number,))
                sync.put('changes/%s/edit:message' % (revision.change.id,), data)
                sync.post('changes/%s/edit:publish' % (revision.change.id,), {})
            change_id = revision.change.id
        sync.submitTask(SyncChangeTask(change_id, priority=self.priority))

class UploadReviewTask(Task):
    def __init__(self, message_key, priority=NORMAL_PRIORITY):
        super(UploadReviewTask, self).__init__(priority)
        self.message_key = message_key

    def __repr__(self):
        return '<UploadReviewTask %s>' % (self.message_key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.message_key == self.message_key):
            return True
        return False

    def run(self, sync):
        app = sync.app

        with app.db.getSession() as session:
            message = session.getMessage(self.message_key)
            if message is None:
                self.log.debug("Message %s has already been uploaded" % (
                    self.message_key))
                return
            change = message.revision.change
        if not change.held:
            self.log.debug("Syncing %s to find out if it should be held" % (change.id,))
            t = SyncChangeTask(change.id)
            t.run(sync)
            self.results += t.results
        submit = False
        change_id = None
        with app.db.getSession() as session:
            message = session.getMessage(self.message_key)
            revision = message.revision
            change = message.revision.change
            if change.held:
                self.log.debug("Not uploading review to %s because it is held" %
                               (change.id,))
                return
            change_id = change.id
            current_revision = change.revisions[-1]
            if change.pending_status and change.status == 'SUBMITTED':
                submit = True
            data = dict(message=message.message,
                        strict_labels=False)
            if revision == current_revision:
                data['labels'] = {}
                for approval in change.draft_approvals:
                    data['labels'][approval.category] = approval.value
                    session.delete(approval)
            comments = {}
            for file in revision.files:
                if file.draft_comments:
                    comment_list = []
                    for comment in file.draft_comments:
                        d = dict(line=comment.line,
                                 message=comment.message)
                        if comment.parent:
                            d['side'] = 'PARENT'
                        comment_list.append(d)
                        session.delete(comment)
                    comments[file.path] = comment_list
            if comments:
                data['comments'] = comments
            session.delete(message)
            # Inside db session for rollback
            sync.post('changes/%s/revisions/%s/review' % (change.id, revision.commit),
                      data)
        if submit:
            # In another db session in case submit fails after posting
            # the message succeeds
            with app.db.getSession() as session:
                change = session.getChangeByID(change_id)
                change.pending_status = False
                change.pending_status_message = None
                sync.post('changes/%s/submit' % (change_id,), {})
        sync.submitTask(SyncChangeTask(change_id, priority=self.priority))

class PruneDatabaseTask(Task):
    def __init__(self, age, priority=NORMAL_PRIORITY):
        super(PruneDatabaseTask, self).__init__(priority)
        self.age = age

    def __repr__(self):
        return '<PruneDatabaseTask %s>' % (self.age,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.age == self.age):
            return True
        return False

    def run(self, sync):
        if not self.age:
            return
        app = sync.app
        with app.db.getSession() as session:
            for change in session.getChanges('status:closed age:%s' % self.age):
                t = PruneChangeTask(change.key, priority=self.priority)
                self.tasks.append(t)
                sync.submitTask(t)
        t = VacuumDatabaseTask(priority=self.priority)
        self.tasks.append(t)
        sync.submitTask(t)

class PruneChangeTask(Task):
    def __init__(self, key, priority=NORMAL_PRIORITY):
        super(PruneChangeTask, self).__init__(priority)
        self.key = key

    def __repr__(self):
        return '<PruneChangeTask %s>' % (self.key,)

    def __eq__(self, other):
        if (other.__class__ == self.__class__ and
            other.key == self.key):
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            change = session.getChange(self.key)
            if not change:
                return
            repo = gitrepo.get_repo(change.project.name, app.config)
            self.log.info("Pruning %s change %s status:%s updated:%s" % (
                change.project.name, change.number, change.status, change.updated))
            change_ref = None
            for revision in change.revisions:
                if change_ref is None:
                    change_ref = '/'.join(revision.fetch_ref.split('/')[:-1])
                self.log.info("Deleting %s ref %s" % (
                    change.project.name, revision.fetch_ref))
                repo.deleteRef(revision.fetch_ref)
            self.log.info("Deleting %s ref %s" % (
                change.project.name, change_ref))
            try:
                repo.deleteRef(change_ref)
            except OSError, e:
                if e.errno not in [errno.EISDIR, errno.EPERM]:
                    raise
            session.delete(change)

class VacuumDatabaseTask(Task):
    def __init__(self, priority=NORMAL_PRIORITY):
        super(VacuumDatabaseTask, self).__init__(priority)

    def __repr__(self):
        return '<VacuumDatabaseTask>'

    def __eq__(self, other):
        if other.__class__ == self.__class__:
            return True
        return False

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            session.vacuum()

class Sync(object):
    def __init__(self, app):
        self.user_agent = 'Gertty/%s %s' % (gertty.version.version_info.release_string(),
                                            requests.utils.default_user_agent())
        self.version = (0, 0, 0)
        self.offline = False
        self.account_id = None
        self.app = app
        self.log = logging.getLogger('gertty.sync')
        self.queue = MultiQueue([HIGH_PRIORITY, NORMAL_PRIORITY, LOW_PRIORITY])
        self.result_queue = Queue.Queue()
        self.session = requests.Session()
        if self.app.config.auth_type == 'basic':
            authclass = requests.auth.HTTPBasicAuth
        else:
            authclass = requests.auth.HTTPDigestAuth
        self.auth = authclass(
            self.app.config.username, self.app.config.password)
        self.submitTask(GetVersionTask(HIGH_PRIORITY))
        self.submitTask(SyncOwnAccountTask(HIGH_PRIORITY))
        self.submitTask(CheckReposTask(HIGH_PRIORITY))
        self.submitTask(UploadReviewsTask(HIGH_PRIORITY))
        self.submitTask(SyncProjectListTask(HIGH_PRIORITY))
        self.submitTask(SyncSubscribedProjectsTask(NORMAL_PRIORITY))
        self.submitTask(SyncSubscribedProjectBranchesTask(LOW_PRIORITY))
        self.submitTask(PruneDatabaseTask(self.app.config.expire_age, LOW_PRIORITY))
        self.periodic_thread = threading.Thread(target=self.periodicSync)
        self.periodic_thread.daemon = True
        self.periodic_thread.start()

    def periodicSync(self):
        hourly = time.time()
        while True:
            try:
                time.sleep(60)
                self.syncSubscribedProjects()
                now = time.time()
                if now-hourly > 3600:
                    hourly = now
                    self.pruneDatabase()
            except Exception:
                self.log.exception('Exception in periodicSync')

    def submitTask(self, task):
        if not self.offline:
            if not self.queue.put(task, task.priority):
                task.complete(False)
        else:
            task.complete(False)

    def run(self, pipe):
        task = None
        while True:
            task = self._run(pipe, task)

    def _run(self, pipe, task=None):
        if not task:
            task = self.queue.get()
        self.log.debug('Run: %s' % (task,))
        try:
            task.run(self)
            task.complete(True)
        except requests.ConnectionError, e:
            self.log.warning("Offline due to: %s" % (e,))
            if not self.offline:
                self.submitTask(GetVersionTask(HIGH_PRIORITY))
                self.submitTask(UploadReviewsTask(HIGH_PRIORITY))
            self.offline = True
            self.app.status.update(offline=True, refresh=False)
            os.write(pipe, 'refresh\n')
            time.sleep(30)
            return task
        except Exception:
            task.complete(False)
            self.log.exception('Exception running task %s' % (task,))
            self.app.status.update(error=True, refresh=False)
        self.offline = False
        self.app.status.update(offline=False, refresh=False)
        for r in task.results:
            self.result_queue.put(r)
        os.write(pipe, 'refresh\n')
        return None

    def url(self, path):
        return self.app.config.url + 'a/' + path

    def get(self, path):
        url = self.url(path)
        self.log.debug('GET: %s' % (url,))
        r = self.session.get(url,
                             verify=self.app.config.verify_ssl,
                             auth=self.auth, timeout=TIMEOUT,
                             headers = {'Accept': 'application/json',
                                        'Accept-Encoding': 'gzip',
                                        'User-Agent': self.user_agent})
        if r.status_code == 200:
            ret = json.loads(r.text[4:])
            if len(ret):
                self.log.debug('200 OK, Received: %s' % (ret,))
            else:
                self.log.debug('200 OK, No body.')
            return ret
        else:
            self.log.warn('HTTP response: %d', r.status_code)

    def post(self, path, data):
        url = self.url(path)
        self.log.debug('POST: %s' % (url,))
        self.log.debug('data: %s' % (data,))
        r = self.session.post(url, data=json.dumps(data).encode('utf8'),
                              verify=self.app.config.verify_ssl,
                              auth=self.auth, timeout=TIMEOUT,
                              headers = {'Content-Type': 'application/json;charset=UTF-8',
                                         'User-Agent': self.user_agent})
        self.log.debug('Received: %s' % (r.text,))
        ret = None
        if r.text and len(r.text)>4:
            try:
                ret = json.loads(r.text[4:])
            except Exception:
                self.log.exception("Unable to parse result %s from post to %s" %
                                   (r.text, url))
        return ret

    def put(self, path, data):
        url = self.url(path)
        self.log.debug('PUT: %s' % (url,))
        self.log.debug('data: %s' % (data,))
        r = self.session.put(url, data=json.dumps(data).encode('utf8'),
                             verify=self.app.config.verify_ssl,
                             auth=self.auth, timeout=TIMEOUT,
                             headers = {'Content-Type': 'application/json;charset=UTF-8',
                                        'User-Agent': self.user_agent})
        self.log.debug('Received: %s' % (r.text,))

    def delete(self, path, data):
        url = self.url(path)
        self.log.debug('DELETE: %s' % (url,))
        self.log.debug('data: %s' % (data,))
        r = self.session.delete(url, data=json.dumps(data).encode('utf8'),
                                verify=self.app.config.verify_ssl,
                                auth=self.auth, timeout=TIMEOUT,
                                headers = {'Content-Type': 'application/json;charset=UTF-8',
                                           'User-Agent': self.user_agent})
        self.log.debug('Received: %s' % (r.text,))

    def syncSubscribedProjects(self):
        task = SyncSubscribedProjectsTask(LOW_PRIORITY)
        self.submitTask(task)
        if task.wait():
            for subtask in task.tasks:
                subtask.wait()

    def pruneDatabase(self):
        task = PruneDatabaseTask(self.app.config.expire_age, LOW_PRIORITY)
        self.submitTask(task)
        if task.wait():
            for subtask in task.tasks:
                subtask.wait()

    def _syncChangeByCommit(self, commit, priority):
        # Accumulate sync change by commit tasks because they often
        # come in batches.  This method assumes it is being called
        # from within the run queue already and therefore does not
        # need to worry about locking the queue.
        task = None
        for task in self.queue.find(SyncChangesByCommitsTask, priority):
            if task.addCommit(commit):
                return
        task = SyncChangesByCommitsTask([commit], priority)
        self.submitTask(task)

    def setRemoteVersion(self, version):
        base = version.split('-')[0]
        parts = base.split('.')
        major = minor = micro = 0
        if len(parts) > 0:
            major = int(parts[0])
        if len(parts) > 1:
            minor = int(parts[1])
        if len(parts) > 2:
            micro = int(parts[2])
        self.version = (major, minor, micro)
        self.log.info("Remote version is: %s (parsed as %s)" % (version, self.version))
