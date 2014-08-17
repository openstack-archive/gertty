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

import datetime

import urwid

from gertty import gitrepo
from gertty import mywid
from gertty import sync
from gertty.view import diff as view_diff
import gertty.view

class ReviewDialog(urwid.WidgetWrap):
    signals = ['save', 'cancel']
    def __init__(self, revision_row):
        self.revision_row = revision_row
        self.change_view = revision_row.change_view
        self.app = self.change_view.app
        save_button = mywid.FixedButton(u'Save')
        cancel_button = mywid.FixedButton(u'Cancel')
        urwid.connect_signal(save_button, 'click',
            lambda button:self._emit('save'))
        urwid.connect_signal(cancel_button, 'click',
            lambda button:self._emit('cancel'))
        buttons = urwid.Columns([('pack', save_button), ('pack', cancel_button)],
                                dividechars=2)
        rows = []
        categories = []
        values = {}
        self.button_groups = {}
        message = ''
        with self.app.db.getSession() as session:
            revision = session.getRevision(self.revision_row.revision_key)
            change = revision.change
            if revision == change.revisions[-1]:
                for label in change.permitted_labels:
                    if label.category not in categories:
                        categories.append(label.category)
                        values[label.category] = []
                    values[label.category].append(label.value)
                pending_approvals = {}
                for approval in change.pending_approvals:
                    pending_approvals[approval.category] = approval
                for category in categories:
                    rows.append(urwid.Text(category))
                    group = []
                    self.button_groups[category] = group
                    current = pending_approvals.get(category)
                    if current is None:
                        current = 0
                    else:
                        current = current.value
                    for value in values[category]:
                        if value > 0:
                            strvalue = '+%s' % value
                        elif value == 0:
                            strvalue = ' 0'
                        else:
                            strvalue = str(value)
                        b = urwid.RadioButton(group, strvalue, state=(value == current))
                        rows.append(b)
                    rows.append(urwid.Divider())
            for m in revision.messages:
                if m.pending:
                    message = m.message
                    break
        self.message = urwid.Edit("Message: \n", edit_text=message, multiline=True)
        rows.append(self.message)
        rows.append(urwid.Divider())
        rows.append(buttons)
        pile = urwid.Pile(rows)
        fill = urwid.Filler(pile, valign='top')
        super(ReviewDialog, self).__init__(urwid.LineBox(fill, 'Review'))

    def save(self):
        approvals = {}
        for category, group in self.button_groups.items():
            for button in group:
                if button.state:
                    approvals[category] = int(button.get_label())
        message = self.message.edit_text.strip()
        self.change_view.saveReview(self.revision_row.revision_key, approvals, message)

    def keypress(self, size, key):
        r = super(ReviewDialog, self).keypress(size, key)
        if r=='esc':
            self._emit('cancel')
            return None
        return r

class ReviewButton(mywid.FixedButton):
    def __init__(self, revision_row):
        super(ReviewButton, self).__init__(('revision-button', u'Review'))
        self.revision_row = revision_row
        self.change_view = revision_row.change_view
        urwid.connect_signal(self, 'click',
            lambda button: self.openReview())

    def openReview(self):
        self.dialog = ReviewDialog(self.revision_row)
        urwid.connect_signal(self.dialog, 'save',
            lambda button: self.closeReview(True))
        urwid.connect_signal(self.dialog, 'cancel',
            lambda button: self.closeReview(False))
        self.change_view.app.popup(self.dialog,
                                   relative_width=50, relative_height=75,
                                   min_width=60, min_height=20)

    def closeReview(self, save):
        if save:
            message_key = self.dialog.save()
        self.change_view.app.backScreen()

class RevisionRow(urwid.WidgetWrap):
    revision_focus_map = {
                          'revision-name': 'focused-revision-name',
                          'revision-commit': 'focused-revision-commit',
                          'revision-comments': 'focused-revision-comments',
                          'revision-drafts': 'focused-revision-drafts',
                          }

    def __init__(self, app, change_view, repo, revision, expanded=False):
        super(RevisionRow, self).__init__(urwid.Pile([]))
        self.app = app
        self.change_view = change_view
        self.revision_key = revision.key
        self.project_name = revision.change.project.name
        self.commit_sha = revision.commit
        self.title = mywid.TextButton(u'', on_press = self.expandContract)
        stats = repo.diffstat(revision.parent, revision.commit)
        table = mywid.Table(columns=3)
        total_added = 0
        total_removed = 0
        for added, removed, filename in stats:
            try:
                added = int(added)
            except ValueError:
                added = 0
            try:
                removed = int(removed)
            except ValueError:
                removed = 0
            total_added += added
            total_removed += removed
            table.addRow([urwid.Text(('filename', filename), wrap='clip'),
                          urwid.Text([('lines-added', '+%i' % (added,)), ', '],
                                     align=urwid.RIGHT),
                          urwid.Text(('lines-removed', '-%i' % (removed,)))])
        table.addRow([urwid.Text(''),
                      urwid.Text([('lines-added', '+%i' % (total_added,)), ', '],
                                 align=urwid.RIGHT),
                      urwid.Text(('lines-removed', '-%i' % (total_removed,)))])
        table = urwid.Padding(table, width='pack')

        focus_map={'revision-button': 'focused-revision-button'}
        self.review_button = ReviewButton(self)
        buttons = [self.review_button,
                   mywid.FixedButton(('revision-button', "Diff"),
                                     on_press=self.diff),
                   mywid.FixedButton(('revision-button', "Local Checkout"),
                                     on_press=self.checkout),
                   mywid.FixedButton(('revision-button', "Local Cherry-Pick"),
                                     on_press=self.cherryPick)]
        buttons = [('pack', urwid.AttrMap(b, None, focus_map=focus_map)) for b in buttons]
        buttons = urwid.Columns(buttons + [urwid.Text('')], dividechars=2)
        buttons = urwid.AttrMap(buttons, 'revision-button')
        self.more = urwid.Pile([table, buttons])
        padded_title = urwid.Padding(self.title, width='pack')
        self.pile = urwid.Pile([padded_title])
        self._w = urwid.AttrMap(self.pile, None, focus_map=self.revision_focus_map)
        self.expanded = False
        self.update(revision)
        if expanded:
            self.expandContract(None)

    def update(self, revision):
        line = [('revision-name', 'Patch Set %s ' % revision.number),
                ('revision-commit', revision.commit)]
        num_drafts = len(revision.pending_comments)
        if num_drafts:
            line.append(('revision-drafts', ' (%s draft%s)' % (
                        num_drafts, num_drafts>1 and 's' or '')))
        num_comments = len(revision.comments) - num_drafts
        if num_comments:
            line.append(('revision-comments', ' (%s inline comment%s)' % (
                        num_comments, num_comments>1 and 's' or '')))
        self.title.text.set_text(line)

    def expandContract(self, button):
        if self.expanded:
            self.pile.contents.pop()
            self.expanded = False
        else:
            self.pile.contents.append((self.more, ('pack', None)))
            self.expanded = True

    def diff(self, button):
        self.change_view.diff(self.revision_key)

    def checkout(self, button):
        repo = self.app.getRepo(self.project_name)
        try:
            repo.checkout(self.commit_sha)
            dialog = mywid.MessageDialog('Checkout', 'Change checked out in %s' % repo.path)
            min_height=8
        except gitrepo.GitCheckoutError as e:
            dialog = mywid.MessageDialog('Error', e.msg)
            min_height=12
        urwid.connect_signal(dialog, 'close',
            lambda button: self.app.backScreen())
        self.app.popup(dialog, min_height=min_height)

    def cherryPick(self, button):
        repo = self.app.getRepo(self.project_name)
        try:
            repo.cherryPick(self.commit_sha)
            dialog = mywid.MessageDialog('Cherry-Pick', 'Change cherry-picked in %s' % repo.path)
            min_height=8
        except gitrepo.GitCheckoutError as e:
            dialog = mywid.MessageDialog('Error', e.msg)
            min_height=12
        urwid.connect_signal(dialog, 'close',
            lambda button: self.app.backScreen())
        self.app.popup(dialog, min_height=min_height)

class ChangeButton(mywid.FixedButton):
    button_left = urwid.Text(u' ')
    button_right = urwid.Text(u' ')

    def __init__(self, change_view, change_key, text):
        super(ChangeButton, self).__init__('')
        self.set_label(text)
        self.change_view = change_view
        self.change_key = change_key
        urwid.connect_signal(self, 'click',
            lambda button: self.openChange())

    def set_label(self, text):
        super(ChangeButton, self).set_label(text)

    def openChange(self):
        self.change_view.app.changeScreen(ChangeView(self.change_view.app, self.change_key))

class ChangeMessageBox(mywid.HyperText):
    def __init__(self, app, message):
        super(ChangeMessageBox, self).__init__(u'')
        lines = message.message.split('\n')
        text = [('change-message-name', message.author.name),
                ('change-message-header', ': '+lines.pop(0)),
                ('change-message-header',
                 message.created.strftime(' (%Y-%m-%d %H:%M:%S%z)'))]
        if lines and lines[-1]:
            lines.append('')
        comment_text = ['\n'.join(lines)]
        for commentlink in app.config.commentlinks:
            comment_text = commentlink.run(app, comment_text)
        self.set_text(text+comment_text)

class CommitMessageBox(mywid.HyperText):
    def __init__(self, app, message):
        self.app = app
        super(CommitMessageBox, self).__init__(message)

    def set_text(self, text):
        text = [text]
        for commentlink in self.app.config.commentlinks:
            text = commentlink.run(self.app, text)
        super(CommitMessageBox, self).set_text(text)

class ChangeView(urwid.WidgetWrap):
    _help = """
<c>      Checkout the most recent revision into the local repo.
<d>      Show the diff of the mont recent revision.
<k>      Toggle the hidden flag for the current change.
<n>      Go to the next change in the list.
<p>      Go to the previous change in the list.
<r>      Leave a review for the most recent revision.
<u>      Back to the list of changes.
<v>      Toggle the reviewed flag for the current change.
<x>      Cherry-pick the most recent revision onto the local repo.
<ctrl-r> Refresh this change.
"""

    def help(self):
        text = self._help
        for k in self.app.config.reviewkeys.values():
            space = max(6 - len(k['key']), 0) * ' '
            action = ', '.join(['{category}:{value}'.format(**a) for a in k['approvals']])
            text += '<%s>%s %s\n' % (k['key'], space, action)
        return text

    def __init__(self, app, change_key):
        super(ChangeView, self).__init__(urwid.Pile([]))
        self.app = app
        self.change_key = change_key
        self.revision_rows = {}
        self.message_rows = {}
        self.last_revision_key = None
        self.change_id_label = urwid.Text(u'', wrap='clip')
        self.owner_label = urwid.Text(u'', wrap='clip')
        self.project_label = urwid.Text(u'', wrap='clip')
        self.branch_label = urwid.Text(u'', wrap='clip')
        self.topic_label = urwid.Text(u'', wrap='clip')
        self.created_label = urwid.Text(u'', wrap='clip')
        self.updated_label = urwid.Text(u'', wrap='clip')
        self.status_label = urwid.Text(u'', wrap='clip')
        change_info = []
        for l, v in [("Change-Id", self.change_id_label),
                     ("Owner", self.owner_label),
                     ("Project", self.project_label),
                     ("Branch", self.branch_label),
                     ("Topic", self.topic_label),
                     ("Created", self.created_label),
                     ("Updated", self.updated_label),
                     ("Status", self.status_label),
                     ]:
            row = urwid.Columns([(12, urwid.Text(('change-header', l), wrap='clip')), v])
            change_info.append(row)
        change_info = urwid.Pile(change_info)
        self.commit_message = CommitMessageBox(app, u'')
        votes = mywid.Table([])
        self.depends_on = urwid.Pile([])
        self.depends_on_rows = {}
        self.needed_by = urwid.Pile([])
        self.needed_by_rows = {}
        self.left_column = urwid.Pile([('pack', change_info),
                                       ('pack', urwid.Divider()),
                                       ('pack', votes),
                                       ('pack', urwid.Divider()),
                                       ('pack', self.depends_on),
                                       ('pack', self.needed_by)])
        top = urwid.Columns([self.left_column, ('weight', 1, self.commit_message)])
        self.listbox = urwid.ListBox(urwid.SimpleFocusListWalker([]))
        self._w.contents.append((self.app.header, ('pack', 1)))
        self._w.contents.append((urwid.Divider(), ('pack', 1)))
        self._w.contents.append((self.listbox, ('weight', 1)))
        self._w.set_focus(2)

        self.listbox.body.append(top)
        self.listbox.body.append(urwid.Divider())
        self.listbox_patchset_start = len(self.listbox.body)

        self.checkGitRepo()
        self.refresh()
        self.listbox.set_focus(0)
        top.set_focus(0)

    def checkGitRepo(self):
        missing_revisions = set()
        change_number = None
        change_id = None
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            change_number = change.number
            change_id = change.id
            repo = self.app.getRepo(change.project.name)
            for revision in change.revisions:
                if not repo.hasCommit(revision.parent):
                    missing_revisions.add(revision.parent)
                if not repo.hasCommit(revision.commit):
                    missing_revisions.add(revision.commit)
                if missing_revisions:
                    break
        if missing_revisions:
            if self.app.sync.offline:
                raise gertty.view.DisplayError("Git commits not present in local repository")
            self.app.log.warning("Missing some commits for change %s %s",
                change_number, missing_revisions)
            task = sync.SyncChangeTask(change_id, force_fetch=True,
                                       priority=sync.HIGH_PRIORITY)
            self.app.sync.submitTask(task)
            succeeded = task.wait(300)
            if not succeeded:
                raise gertty.view.DisplayError("Git commits not present in local repository")

    def refresh(self):
        change_info = []
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            if change.reviewed:
                reviewed = ' (reviewed)'
            else:
                reviewed = ''
            if change.hidden:
                hidden = ' (hidden)'
            else:
                hidden = ''
            self.title = 'Change %s%s%s' % (change.number, reviewed, hidden)
            self.app.status.update(title=self.title)
            self.project_key = change.project.key
            self.change_rest_id = change.id

            self.change_id_label.set_text(('change-data', change.change_id))
            self.owner_label.set_text(('change-data', change.owner.name))
            self.project_label.set_text(('change-data', change.project.name))
            self.branch_label.set_text(('change-data', change.branch))
            self.topic_label.set_text(('change-data', change.topic or ''))
            self.created_label.set_text(('change-data', str(change.created)))
            self.updated_label.set_text(('change-data', str(change.updated)))
            self.status_label.set_text(('change-data', change.status))
            self.commit_message.set_text(change.revisions[-1].message)

            categories = []
            max_values = {}
            min_values = {}
            approval_headers = [urwid.Text(('table-header', 'Name'))]
            for label in change.labels:
                if label.value > max_values.get(label.category, 0):
                    max_values[label.category] = label.value
                if label.value < min_values.get(label.category, 0):
                    min_values[label.category] = label.value
                if label.category in categories:
                    continue
                approval_headers.append(urwid.Text(('table-header', label.category)))
                categories.append(label.category)
            votes = mywid.Table(approval_headers)
            approvals_for_name = {}
            for approval in change.approvals:
                approvals = approvals_for_name.get(approval.reviewer.name)
                if not approvals:
                    approvals = {}
                    row = []
                    row.append(urwid.Text(('reviewer-name', approval.reviewer.name)))
                    for i, category in enumerate(categories):
                        w = urwid.Text(u'', align=urwid.CENTER)
                        approvals[category] = w
                        row.append(w)
                    approvals_for_name[approval.reviewer.name] = approvals
                    votes.addRow(row)
                if str(approval.value) != '0':
                    if approval.value > 0:
                        val = '+%i' % approval.value
                        if approval.value == max_values.get(approval.category):
                            val = ('max-label', val)
                        else:
                            val = ('positive-label', val)
                    else:
                        val = '%i' % approval.value
                        if approval.value == min_values.get(approval.category):
                            val = ('min-label', val)
                        else:
                            val = ('negative-label', val)
                    approvals[approval.category].set_text(val)
            votes = urwid.Padding(votes, width='pack')

            # TODO: update the existing table rather than replacing it
            # wholesale.  It will become more important if the table
            # gets selectable items (like clickable names).
            self.left_column.contents[2] = (votes, ('pack', None))

            self.refreshDependencies(session, change)

            repo = self.app.getRepo(change.project.name)
            # The listbox has both revisions and messages in it (and
            # may later contain the vote table and change header), so
            # keep track of the index separate from the loop.
            listbox_index = self.listbox_patchset_start
            for revno, revision in enumerate(change.revisions):
                self.last_revision_key = revision.key
                row = self.revision_rows.get(revision.key)
                if not row:
                    row = RevisionRow(self.app, self, repo, revision,
                                      expanded=(revno==len(change.revisions)-1))
                    self.listbox.body.insert(listbox_index, row)
                    self.revision_rows[revision.key] = row
                row.update(revision)
                # Revisions are extremely unlikely to be deleted, skip
                # that case.
                listbox_index += 1
            if len(self.listbox.body) == listbox_index:
                self.listbox.body.insert(listbox_index, urwid.Divider())
                listbox_index += 1
            for message in change.messages:
                row = self.message_rows.get(message.key)
                if not row:
                    row = ChangeMessageBox(self.app, message)
                    self.listbox.body.insert(listbox_index, row)
                    self.message_rows[message.key] = row
                # Messages are extremely unlikely to be deleted, skip
                # that case.
                listbox_index += 1

    def _updateDependenciesWidget(self, changes, widget, widget_rows, header):
        if not changes:
            if len(widget.contents) > 0:
                widget.contents[:] = []
            return

        if len(widget.contents) == 0:
            widget.contents.append((urwid.Text(('table-header', header)),
                                    widget.options()))

        unseen_keys = set(widget_rows.keys())
        i = 1
        for key, subject in changes.items():
            row = widget_rows.get(key)
            if not row:
                row = urwid.AttrMap(urwid.Padding(ChangeButton(self, key, subject), width='pack'),
                                    'link', focus_map={None: 'focused-link'})
                widget.contents.insert(i, (row, widget.options('pack')))
                if not widget.focus.selectable():
                    widget.set_focus(i)
                if not self.left_column.focus.selectable():
                    self.left_column.set_focus(widget)
                widget_rows[key] = row
            else:
                row.original_widget.original_widget.set_label(subject)
                unseen_keys.remove(key)
            i += 1
        for key in unseen_keys:
            row = widget_rows[key]
            widget.contents.remove(row)
            del widget_rows[key]

    def refreshDependencies(self, session, change):
        revision = change.revisions[-1]

        # Handle depends-on
        parents = {}
        parent = session.getRevisionByCommit(revision.parent)
        if parent and parent.change.status != 'MERGED':
            parents[parent.change.key] = parent.change.subject
        self._updateDependenciesWidget(parents,
                                       self.depends_on, self.depends_on_rows,
                                       header='Depends on:')

        # Handle needed-by
        children = dict((r.change.key, r.change.subject)
                        for r in session.getRevisionsByParent(revision.commit)
                        if r.change.status != 'MERGED')
        self._updateDependenciesWidget(children,
                                       self.needed_by, self.needed_by_rows,
                                       header='Needed by:')


    def toggleReviewed(self):
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            change.reviewed = not change.reviewed

    def toggleHidden(self):
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            change.hidden = not change.hidden

    def keypress(self, size, key):
        r = super(ChangeView, self).keypress(size, key)
        if r == 'v':
            self.toggleReviewed()
            self.refresh()
            return None
        if r == 'k':
            self.toggleHidden()
            self.refresh()
            return None
        if r == 'r':
            row = self.revision_rows[self.last_revision_key]
            row.review_button.openReview()
            return None
        if r == 'd':
            row = self.revision_rows[self.last_revision_key]
            row.diff(None)
            return None
        if r == 'c':
            row = self.revision_rows[self.last_revision_key]
            row.checkout(None)
            return None
        if r == 'x':
            row = self.revision_rows[self.last_revision_key]
            row.cherryPick(None)
            return None
        if r == 'u':
            widget = self.app.findChangeList()
            self.app.backScreen(widget)
            return None
        if r in ['n', 'p']:
            widget = self.app.findChangeList()
            if r == 'n':
                new_change_key = widget.getNextChangeKey(self.change_key)
            else:
                new_change_key = widget.getPrevChangeKey(self.change_key)
            if new_change_key:
                try:
                    view = ChangeView(self.app, new_change_key)
                    self.app.changeScreen(view, push=False)
                except gertty.view.DisplayError as e:
                    self.app.error(e.message)
            return None
        if r == 'ctrl r':
            self.app.sync.submitTask(
                sync.SyncChangeTask(self.change_rest_id, priority=sync.HIGH_PRIORITY))
            self.app.status.update()
            return None
        if r in self.app.config.reviewkeys:
            self.reviewKey(self.app.config.reviewkeys[r])
            return None
        return r

    def diff(self, revision_key):
        self.app.changeScreen(view_diff.DiffView(self.app, revision_key))

    def reviewKey(self, reviewkey):
        approvals = {}
        for a in reviewkey['approvals']:
            approvals[a['category']] = a['value']
        self.app.log.debug("Reviewkey %s with approvals %s" %
                           (reviewkey['key'], approvals))
        row = self.revision_rows[self.last_revision_key]
        self.saveReview(row.revision_key, approvals, '')

    def saveReview(self, revision_key, approvals, message):
        message_key = None
        with self.app.db.getSession() as session:
            account = session.getAccountByUsername(self.app.config.username)
            revision = session.getRevision(revision_key)
            change = revision.change
            pending_approvals = {}
            for approval in change.pending_approvals:
                pending_approvals[approval.category] = approval

            categories = set()
            for label in change.permitted_labels:
                categories.add(label.category)
            for category in categories:
                value = approvals.get(category, 0)
                approval = pending_approvals.get(category)
                if not approval:
                    approval = change.createApproval(account, category, 0, pending=True)
                    pending_approvals[category] = approval
                approval.value = value
            pending_message = None
            for m in revision.messages:
                if m.pending:
                    pending_message = m
                    break
            if not pending_message:
                pending_message = revision.createMessage(None, account,
                                                         datetime.datetime.utcnow(),
                                                         '', pending=True)
            pending_message.message = message
            message_key = pending_message.key
            change.reviewed = True
        self.app.sync.submitTask(
            sync.UploadReviewTask(message_key, sync.HIGH_PRIORITY))
        self.refresh()
