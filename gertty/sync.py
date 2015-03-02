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

HIGH_PRIORITY=0
NORMAL_PRIORITY=1
LOW_PRIORITY=2

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
        self.condition.acquire()
        try:
            self.queues[priority].append(item)
            self.condition.notify()
        finally:
            self.condition.release()

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

class SyncOwnAccountTask(Task):
    def __repr__(self):
        return '<SyncOwnAccountTask>'

    def run(self, sync):
        app = sync.app
        remote = sync.get('accounts/self')
        sync.account_id = remote['_account_id']
        with app.db.getSession() as session:
            session.getAccountByID(remote['_account_id'],
                                   remote.get('name'),
                                   remote.get('username'),
                                   remote.get('email'))

class SyncProjectListTask(Task):
    def __repr__(self):
        return '<SyncProjectListTask>'

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

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            keys = [p.key for p in session.getProjects(subscribed=True)]
        for i in range(0, len(keys), 10):
            t = SyncProjectTask(keys[i:i+10], self.priority)
            self.tasks.append(t)
            sync.submitTask(t)

class SyncProjectTask(Task):
    _closed_statuses = ['MERGED', 'ABANDONED']

    def __init__(self, project_keys, priority=NORMAL_PRIORITY):
        super(SyncProjectTask, self).__init__(priority)
        if type(project_keys) == int:
            project_keys = [project_keys]
        self.project_keys = project_keys

    def __repr__(self):
        return '<SyncProjectTask %s>' % (self.project_keys,)

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
            if c['id'] in change_ids or (c['status'] not in self._closed_statuses):
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

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            project = session.getProject(self.project_key)
            project.updated = self.updated

class SyncChangeByCommitTask(Task):
    def __init__(self, commit, priority=NORMAL_PRIORITY):
        super(SyncChangeByCommitTask, self).__init__(priority)
        self.commit = commit

    def __repr__(self):
        return '<SyncChangeByCommitTask %s>' % (self.commit,)

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            query = 'commit:%s' % self.commit
        changes = sync.get('changes/?q=%s' % query)
        self.log.debug('Query: %s ' % (query,))
        for c in changes:
            sync.submitTask(SyncChangeTask(c['id'], priority=self.priority))
            self.log.debug("Sync change %s for its commit %s" % (c['id'], self.commit))

class SyncChangeByNumberTask(Task):
    def __init__(self, number, priority=NORMAL_PRIORITY):
        super(SyncChangeByNumberTask, self).__init__(priority)
        self.number = number

    def __repr__(self):
        return '<SyncChangeByNumberTask %s>' % (self.number,)

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
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

    def run(self, sync):
        start_time = time.time()
        app = sync.app
        remote_change = sync.get('changes/%s?o=DETAILED_LABELS&o=ALL_REVISIONS&o=ALL_COMMITS&o=MESSAGES&o=DETAILED_ACCOUNTS&o=CURRENT_ACTIONS' % self.change_id)
        # Perform subqueries this task will need outside of the db session
        for remote_commit, remote_revision in remote_change.get('revisions', {}).items():
            remote_comments_data = sync.get('changes/%s/revisions/%s/comments' % (self.change_id, remote_commit))
            remote_revision['_gertty_remote_comments_data'] = remote_comments_data
        fetches = collections.defaultdict(list)
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
            repo = app.getRepo(change.project.name)
            new_revision = False
            for remote_commit, remote_revision in remote_change.get('revisions', {}).items():
                revision = session.getRevisionByCommit(remote_commit)
                # TODO: handle multiple parents
                url = sync.app.config.url + change.project.name
                if 'anonymous http' in remote_revision['fetch']:
                    ref = remote_revision['fetch']['anonymous http']['ref']
                    auth = False
                else:
                    auth = True
                    ref = remote_revision['fetch']['http']['ref']
                    url = list(urlparse.urlsplit(url))
                    url[1] = '%s:%s@%s' % (
                        urllib.quote_plus(sync.app.config.username),
                        urllib.quote_plus(sync.app.config.password), url[1])
                    url = urlparse.urlunsplit(url)
                if (not revision) or self.force_fetch:
                    fetches[url].append('+%(ref)s:%(ref)s' % dict(ref=ref))
                if not revision:
                    revision = change.createRevision(remote_revision['_number'],
                                                     remote_revision['commit']['message'], remote_commit,
                                                     remote_revision['commit']['parents'][0]['commit'],
                                                     auth, ref)
                    self.log.info("Created new revision %s for change %s revision %s in local DB.", revision.key, self.change_id, remote_revision['_number'])
                    new_revision = True
                revision.message = remote_revision['commit']['message']
                # TODO: handle multiple parents
                parent_revision = session.getRevisionByCommit(revision.parent)
                actions = remote_revision.get('actions', {})
                revision.can_submit = 'submit' in actions
                # TODO: use a singleton list of closed states
                if not parent_revision and change.status not in ['MERGED', 'ABANDONED']:
                    sync.submitTask(SyncChangeByCommitTask(revision.parent, self.priority))
                    self.log.debug("Change %s revision %s needs parent commit %s synced" %
                                   (change.id, remote_revision['_number'], revision.parent))
                result.updateRelatedChanges(session, change)
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
                            comment = revision.createComment(remote_comment['id'], account,
                                                             remote_comment.get('in_reply_to'),
                                                             created,
                                                             remote_file, parent, remote_comment.get('line'),
                                                             remote_comment['message'])
                            self.log.info("Created new comment %s for revision %s in local DB.", comment.key, revision.key)
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
            for approval in change.approvals:
                key = '%s~%s' % (approval.category, approval.reviewer.id)
                if key in local_approvals:
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
    #   for any newly cloned project, run checkrevisionstask on that project
    #   if --fetch-missing-refs is supplied, run crt on every project
    def __repr__(self):
        return '<CheckReposTask>'

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            projects = session.getProjects(subscribed=True)
        for project in projects:
            try:
                repo = app.getRepo(project.name)
                if repo.newly_cloned or app.fetch_missing_refs:
                    sync.submitTask(CheckRevisionsTask(key,
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

    def run(self, sync):
        app = sync.app
        to_fetch = collections.defaultdict(list)
        with app.db.getSession() as session:
            project = session.getProject(self.project_key)
            repo = app.getRepo(project.name)
            for change in project.open_changes:
                for revision in change.revisions:
                    if not (repo.hasCommit(revision.parent) and
                            repo.hasCommit(revision.commit)):
                        if revision.fetch_ref:
                            to_fetch[(project.name, revision.fetch_auth)
                                     ].append(revision.fetch_ref)
        for (name, auth), refs in to_fetch.items():
            sync.submitTask(FetchRefTask(name, refs, auth, priority=self.priority))

class FetchRefTask(Task):
    def __init__(self, project_name, refs, auth, priority=NORMAL_PRIORITY):
        super(FetchRefTask, self).__init__(priority)
        self.project_name = project_name
        self.refs = refs
        self.auth = auth

    def __repr__(self):
        return '<FetchRefTask %s %s>' % (self.project_name, self.refs)

    def run(self, sync):
        # TODO: handle multiple parents
        url = sync.app.config.url + self.project_name
        if self.auth:
            url = list(urlparse.urlsplit(url))
            url[1] = '%s:%s@%s' % (sync.app.config.username,
                                   sync.app.config.password, url[1])
            url = urlparse.urlunsplit(url)
        self.log.debug("git fetch %s %s" % (url, self.refs))
        repo = sync.app.getRepo(self.project_name)
        refs = ['+%(ref)s:%(ref)s' % dict(ref=ref) for ref in self.refs]
        try:
            repo.fetch(url, refs)
        except Exception:
            # Backwards compat with GitPython before the multi-ref fetch
            # patch.
            # (https://github.com/gitpython-developers/GitPython/pull/170)
            for ref in refs:
                self.log.debug("git fetch %s %s" % (url, ref))
                repo.fetch(url, ref)

class UploadReviewsTask(Task):
    def __repr__(self):
        return '<UploadReviewsTask>'

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

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            revision = session.getRevision(self.revision_key)
            revision.pending_message = False
            data = dict(message=revision.message)
            # Inside db session for rollback
            ret = sync.post('changes/%s/revisions/%s/message' %
                            (revision.change.id, revision.commit),
                            data)
            change_id = revision.change.id
        sync.submitTask(SyncChangeTask(change_id, priority=self.priority))

class UploadReviewTask(Task):
    def __init__(self, message_key, priority=NORMAL_PRIORITY):
        super(UploadReviewTask, self).__init__(priority)
        self.message_key = message_key

    def __repr__(self):
        return '<UploadReviewTask %s>' % (self.message_key,)

    def run(self, sync):
        app = sync.app
        submit = False
        change_id = None
        with app.db.getSession() as session:
            message = session.getMessage(self.message_key)
            revision = message.revision
            change = message.revision.change
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
            if revision.draft_comments:
                data['comments'] = {}
                last_file = None
                comment_list = []
                for comment in revision.draft_comments:
                    if comment.file != last_file:
                        last_file = comment.file
                        comment_list = []
                        data['comments'][comment.file] = comment_list
                    d = dict(line=comment.line,
                             message=comment.message)
                    if comment.parent:
                        d['side'] = 'PARENT'
                    comment_list.append(d)
                    session.delete(comment)
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

class Sync(object):
    def __init__(self, app):
        self.user_agent = 'Gertty/%s %s' % (gertty.version.version_info.version_string(),
                                            requests.utils.default_user_agent())
        self.offline = False
        self.account_id = None
        self.app = app
        self.log = logging.getLogger('gertty.sync')
        self.queue = MultiQueue([HIGH_PRIORITY, NORMAL_PRIORITY, LOW_PRIORITY])
        self.result_queue = Queue.Queue()
        # Disable InsecureRequestWarning when certificate validation is disabled
        if not self.app.config.verify_ssl:
            requests.packages.urllib3.disable_warnings()
        self.session = requests.Session()
        if self.app.config.auth_type == 'basic':
            authclass = requests.auth.HTTPBasicAuth
        else:
            authclass = requests.auth.HTTPDigestAuth
        self.auth = authclass(
            self.app.config.username, self.app.config.password)
        self.submitTask(SyncOwnAccountTask(HIGH_PRIORITY))
        self.submitTask(CheckReposTask(HIGH_PRIORITY))
        self.submitTask(UploadReviewsTask(HIGH_PRIORITY))
        self.submitTask(SyncProjectListTask(HIGH_PRIORITY))
        self.submitTask(SyncSubscribedProjectsTask(NORMAL_PRIORITY))
        self.submitTask(SyncSubscribedProjectBranchesTask(LOW_PRIORITY))
        self.periodic_thread = threading.Thread(target=self.periodicSync)
        self.periodic_thread.daemon = True
        self.periodic_thread.start()

    def periodicSync(self):
        while True:
            try:
                time.sleep(60)
                self.syncSubscribedProjects()
            except Exception:
                self.log.exception('Exception in periodicSync')

    def submitTask(self, task):
        if not self.offline:
            self.queue.put(task, task.priority)

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
                self.submitTask(SyncSubscribedProjectsTask(HIGH_PRIORITY))
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
                         auth=self.auth,
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
                          auth=self.auth,
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
                             auth=self.auth,
                             headers = {'Content-Type': 'application/json;charset=UTF-8',
                                        'User-Agent': self.user_agent})
        self.log.debug('Received: %s' % (r.text,))

    def delete(self, path, data):
        url = self.url(path)
        self.log.debug('DELETE: %s' % (url,))
        self.log.debug('data: %s' % (data,))
        r = self.session.delete(url, data=json.dumps(data).encode('utf8'),
                                verify=self.app.config.verify_ssl,
                                auth=self.auth,
                                headers = {'Content-Type': 'application/json;charset=UTF-8',
                                           'User-Agent': self.user_agent})
        self.log.debug('Received: %s' % (r.text,))

    def syncSubscribedProjects(self):
        task = SyncSubscribedProjectsTask(LOW_PRIORITY)
        self.submitTask(task)
        task.wait()
        for subtask in task.tasks:
            subtask.wait()
