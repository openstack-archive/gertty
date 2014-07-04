# Copyright 2014 OpenStack Foundation
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
import threading
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

class Task(object):
    def __init__(self, priority=NORMAL_PRIORITY):
        self.log = logging.getLogger('gertty.sync')
        self.priority = priority
        self.succeeded = None
        self.event = threading.Event()

    def complete(self, success):
        self.succeeded = success
        self.event.set()

    def wait(self, timeout=None):
        self.event.wait(timeout)
        return self.succeeded

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
                session.createProject(name, description=p.get('description', ''))

class SyncSubscribedProjectsTask(Task):
    def __repr__(self):
        return '<SyncSubscribedProjectsTask>'

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            for p in session.getProjects(subscribed=True):
                sync.submitTask(SyncProjectTask(p.key, self.priority))

class SyncProjectTask(Task):
    _closed_statuses = ['MERGED', 'ABANDONED']

    def __init__(self, project_key, priority=NORMAL_PRIORITY):
        super(SyncProjectTask, self).__init__(priority)
        self.project_key = project_key

    def __repr__(self):
        return '<SyncProjectTask %s>' % (self.project_key,)

    def run(self, sync):
        app = sync.app
        now = datetime.datetime.utcnow()
        with app.db.getSession() as session:
            project = session.getProject(self.project_key)
            query = 'project:%s' % project.name
            if project.updated:
                # Allow 4 seconds for request time, etc.
                query += ' -age:%ss' % (int(math.ceil((now-project.updated).total_seconds())) + 4,)
        changes = sync.get('changes/?q=%s' % query)
        self.log.debug('Query: %s ' % (query,))
        with app.db.getSession() as session:
            for c in changes:
                # For now, just sync open changes or changes already
                # in the db optionally we could sync all changes ever
                change = session.getChangeByID(c['id'])
                if change or (c['status'] not in self._closed_statuses):
                    sync.submitTask(SyncChangeTask(c['id'], priority=self.priority))
                    self.log.debug("Change %s update %s" % (c['id'], c['updated']))
        sync.submitTask(SetProjectUpdatedTask(self.project_key, now, priority=self.priority))

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
        with app.db.getSession() as session:
            for c in changes:
                sync.submitTask(SyncChangeTask(c['id'], priority=self.priority))
                self.log.debug("Sync change %s for its commit %s" % (c['id'], self.commit))

class SyncChangeByNumberTask(Task):
    def __init__(self, number, priority=NORMAL_PRIORITY):
        super(SyncChangeByNumberTask, self).__init__(priority)
        self.number = number
        self.tasks = []

    def __repr__(self):
        return '<SyncChangeByNumberTask %s>' % (self.number,)

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            query = '%s' % self.number
        changes = sync.get('changes/?q=%s' % query)
        self.log.debug('Query: %s ' % (query,))
        with app.db.getSession() as session:
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
        app = sync.app
        remote_change = sync.get('changes/%s?o=DETAILED_LABELS&o=ALL_REVISIONS&o=ALL_COMMITS&o=MESSAGES&o=DETAILED_ACCOUNTS' % self.change_id)
        # Perform subqueries this task will need outside of the db session
        for remote_commit, remote_revision in remote_change.get('revisions', {}).items():
            remote_comments_data = sync.get('changes/%s/revisions/%s/comments' % (self.change_id, remote_commit))
            remote_revision['_gertty_remote_comments_data'] = remote_comments_data
        fetches = collections.defaultdict(list)
        with app.db.getSession() as session:
            change = session.getChangeByID(self.change_id)
            if not change:
                project = session.getProjectByName(remote_change['project'])
                created = dateutil.parser.parse(remote_change['created'])
                updated = dateutil.parser.parse(remote_change['updated'])
                change = project.createChange(remote_change['id'], remote_change['_number'],
                                              remote_change['branch'], remote_change['change_id'],
                                              remote_change['owner']['name'],
                                              remote_change['subject'], created,
                                              updated, remote_change['status'],
                                              topic=remote_change.get('topic'))
            change.status = remote_change['status']
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
                    url[1] = '%s:%s@%s' % (sync.app.config.username,
                                           sync.app.config.password, url[1])
                    url = urlparse.urlunsplit(url)
                if (not revision) or self.force_fetch:
                    fetches[url].append('+%(ref)s:%(ref)s' % dict(ref=ref))
                if not revision:
                    revision = change.createRevision(remote_revision['_number'],
                                                     remote_revision['commit']['message'], remote_commit,
                                                     remote_revision['commit']['parents'][0]['commit'],
                                                     auth, ref)
                    new_revision = True
                # TODO: handle multiple parents
                parent_revision = session.getRevisionByCommit(revision.parent)
                # TODO: use a singleton list of closed states
                if not parent_revision and change.status not in ['MERGED', 'ABANDONED']:
                    sync.submitTask(SyncChangeByCommitTask(revision.parent, self.priority))
                    self.log.debug("Change %s revision %s needs parent commit %s synced" %
                                   (change.id, remote_revision['_number'], revision.parent))
                remote_comments_data = remote_revision['_gertty_remote_comments_data']
                for remote_file, remote_comments in remote_comments_data.items():
                    for remote_comment in remote_comments:
                        comment = session.getCommentByID(remote_comment['id'])
                        if not comment:
                            # Normalize updated -> created
                            created = dateutil.parser.parse(remote_comment['updated'])
                            parent = False
                            if remote_comment.get('side', '') == 'PARENT':
                                parent = True
                            comment = revision.createComment(remote_comment['id'],
                                                             remote_comment.get('in_reply_to'),
                                                             created, remote_comment['author']['name'],
                                                             remote_file, parent, remote_comment.get('line'),
                                                             remote_comment['message'])
            new_message = False
            for remote_message in remote_change.get('messages', []):
                message = session.getMessageByID(remote_message['id'])
                if not message:
                    revision = session.getRevisionByNumber(change, remote_message['_revision_number'])
                    # Normalize date -> created
                    created = dateutil.parser.parse(remote_message['date'])
                    if 'author' in remote_message:
                        author_name = remote_message['author']['name']
                        if remote_message['author'].get('username') != app.config.username:
                            new_message = True
                    else:
                        author_name = 'Gerrit Code Review'
                    message = revision.createMessage(remote_message['id'], created,
                                                     author_name,
                                                     remote_message['message'])
            remote_approval_entries = {}
            remote_label_entries = {}
            user_voted = False
            for remote_label_name, remote_label_dict in remote_change.get('labels', {}).items():
                for remote_approval in remote_label_dict.get('all', []):
                    if remote_approval.get('value') is None:
                        continue
                    remote_approval['category'] = remote_label_name
                    key = '%s~%s' % (remote_approval['category'], remote_approval['name'])
                    remote_approval_entries[key] = remote_approval
                    if remote_approval.get('username', None) == app.config.username and int(remote_approval['value']) != 0:
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
                key = '%s~%s' % (approval.category, approval.name)
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
                change.createApproval(remote_approval['name'],
                                      remote_approval['category'],
                                      remote_approval['value'])

            for key in remote_label_keys-local_label_keys:
                remote_label = remote_label_entries[key]
                change.createLabel(remote_label['category'],
                                   remote_label['value'],
                                   remote_label['description'])

            for key in remote_approval_keys.intersection(local_approval_keys):
                local_approval = local_approvals[key]
                remote_approval = remote_approval_entries[key]
                local_approval.value = remote_approval['value']

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
                    change.reviewed = False
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

class CheckRevisionsTask(Task):
    def __repr__(self):
        return '<CheckRevisionsTask>'

    def run(self, sync):
        app = sync.app
        to_fetch = collections.defaultdict(list)
        with app.db.getSession() as session:
            for project in session.getProjects():
                if not project.open_changes:
                    continue
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
            for m in session.getPendingMessages():
                sync.submitTask(UploadReviewTask(m.key, self.priority))

class UploadReviewTask(Task):
    def __init__(self, message_key, priority=NORMAL_PRIORITY):
        super(UploadReviewTask, self).__init__(priority)
        self.message_key = message_key

    def __repr__(self):
        return '<UploadReviewTask %s>' % (self.message_key,)

    def run(self, sync):
        app = sync.app
        with app.db.getSession() as session:
            message = session.getMessage(self.message_key)
            revision = message.revision
            change = message.revision.change
            current_revision = change.revisions[-1]
            data = dict(message=message.message,
                        strict_labels=False)
            if revision == current_revision:
                data['labels'] = {}
                for approval in change.pending_approvals:
                    data['labels'][approval.category] = approval.value
                    session.delete(approval)
            if revision.pending_comments:
                data['comments'] = {}
                last_file = None
                comment_list = []
                for comment in revision.pending_comments:
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
            sync.submitTask(SyncChangeTask(change.id, priority=self.priority))

class Sync(object):
    def __init__(self, app):
        self.offline = False
        self.app = app
        self.log = logging.getLogger('gertty.sync')
        self.queue = MultiQueue([HIGH_PRIORITY, NORMAL_PRIORITY, LOW_PRIORITY])
        self.session = requests.Session()
        self.submitTask(UploadReviewsTask(HIGH_PRIORITY))
        self.submitTask(SyncProjectListTask(HIGH_PRIORITY))
        self.submitTask(SyncSubscribedProjectsTask(HIGH_PRIORITY))
        self.submitTask(CheckRevisionsTask(LOW_PRIORITY))
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
            self.app.status.update(offline=True)
            os.write(pipe, 'refresh\n')
            time.sleep(30)
            return task
        except Exception:
            task.complete(False)
            self.log.exception('Exception running task %s' % (task,))
            self.app.status.update(error=True)
        self.offline = False
        self.app.status.update(offline=False)
        os.write(pipe, 'refresh\n')
        return None

    def url(self, path):
        return self.app.config.url + 'a/' + path

    def get(self, path):
        url = self.url(path)
        self.log.debug('GET: %s' % (url,))
        r = self.session.get(url,
                         verify=self.app.config.verify_ssl,
                         auth=requests.auth.HTTPDigestAuth(self.app.config.username,
                                                           self.app.config.password),
                         headers = {'Accept': 'application/json',
                                    'Accept-Encoding': 'gzip'})
        self.log.debug('Received: %s' % (r.text,))
        ret = json.loads(r.text[4:])
        return ret

    def post(self, path, data):
        url = self.url(path)
        self.log.debug('POST: %s' % (url,))
        self.log.debug('data: %s' % (data,))
        r = self.session.post(url, data=json.dumps(data).encode('utf8'),
                          verify=self.app.config.verify_ssl,
                          auth=requests.auth.HTTPDigestAuth(self.app.config.username,
                                                            self.app.config.password),
                          headers = {'Content-Type': 'application/json;charset=UTF-8'})
        self.log.debug('Received: %s' % (r.text,))

    def syncSubscribedProjects(self):
        keys = []
        with self.app.db.getSession() as session:
            for p in session.getProjects(subscribed=True):
                keys.append(p.key)
        for key in keys:
            t = SyncProjectTask(key, LOW_PRIORITY)
            self.submitTask(t)
            t.wait()
