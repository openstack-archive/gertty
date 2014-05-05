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

import datetime

import urwid

from gertty import gitrepo
from gertty import mywid
from gertty import sync
from gertty.view import diff as view_diff

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
        message_key = None
        with self.app.db.getSession() as session:
            revision = session.getRevision(self.revision_row.revision_key)
            change = revision.change
            pending_approvals = {}
            for approval in change.pending_approvals:
                pending_approvals[approval.category] = approval
            for category, group in self.button_groups.items():
                approval = pending_approvals.get(category)
                if not approval:
                    approval = change.createApproval(u'(draft)', category, 0, pending=True)
                    pending_approvals[category] = approval
                for button in group:
                    if button.state:
                        approval.value = int(button.get_label())
            message = None
            for m in revision.messages:
                if m.pending:
                    message = m
                    break
            if not message:
                message = revision.createMessage(None,
                                                 datetime.datetime.utcnow(),
                                                 u'(draft)', '', pending=True)
            message.message = self.message.edit_text.strip()
            message_key = message.key
            change.reviewed = True
        return message_key

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
            self.change_view.app.sync.submitTask(
                sync.UploadReviewTask(message_key, sync.HIGH_PRIORITY))
            self.change_view.refresh()
        self.change_view.app.backScreen()

class RevisionRow(urwid.WidgetWrap):
    revision_focus_map = {
                          'revision-name': 'reversed-revision-name',
                          'revision-commit': 'reversed-revision-commit',
                          'revision-comments': 'reversed-revision-comments',
                          'revision-drafts': 'reversed-revision-drafts',
                          }

    def __init__(self, app, change_view, repo, revision, expanded=False):
        super(RevisionRow, self).__init__(urwid.Pile([]))
        self.app = app
        self.change_view = change_view
        self.revision_key = revision.key
        self.project_name = revision.change.project.name
        self.commit_sha = revision.commit
        line = [('revision-name', 'Patch Set %s ' % revision.number),
                ('revision-commit', revision.commit)]
        if len(revision.pending_comments):
            line.append(('revision-drafts', ' (%s drafts)' % len(revision.pending_comments)))
        if len(revision.comments):
            line.append(('revision-comments', ' (%s inline comments)' % len(revision.comments)))
        self.title = mywid.TextButton(line, on_press = self.expandContract)
        stats = repo.diffstat(revision.parent, revision.commit)
        rows = []
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
            rows.append(urwid.Columns([urwid.Text(filename),
                                       (10, urwid.Text('+%s, -%s' % (added, removed))),
                                       ]))
        rows.append(urwid.Columns([urwid.Text(''),
                                   (10, urwid.Text('+%s, -%s' % (total_added, total_removed))),
                                   ]))
        table = urwid.Pile(rows)


        focus_map={'revision-button':'selected-revision-button'}
        self.review_button = ReviewButton(self)
        buttons = [self.review_button,
                   mywid.FixedButton(('revision-button', "Diff"),
                                     on_press=self.diff),
                   mywid.FixedButton(('revision-button', "Checkout"),
                                     on_press=self.checkout)]
        buttons = [('pack', urwid.AttrMap(b, None, focus_map=focus_map)) for b in buttons]
        buttons = urwid.Columns(buttons + [urwid.Text('')], dividechars=2)
        buttons = urwid.AttrMap(buttons, 'revision-button')
        self.more = urwid.Pile([table, buttons])
        self.pile = urwid.Pile([self.title])
        self._w = urwid.AttrMap(self.pile, None, focus_map=self.revision_focus_map)
        self.expanded = False
        if expanded:
            self.expandContract(None)

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

class ChangeMessageBox(urwid.Text):
    def __init__(self, message):
        super(ChangeMessageBox, self).__init__(u'')
        lines = message.message.split('\n')
        text = [('change-message-name', message.name),
                ('change-message-header', ': '+lines.pop(0))]
        if lines and lines[-1]:
            lines.append('')
        text += '\n'.join(lines)
        self.set_text(text)

class ChangeView(urwid.WidgetWrap):
    help = mywid.GLOBAL_HELP + """
This Screen
===========
<R>   Toggle the reviewed flag for the current change.
<c>   Checkout the most recent revision.
<d>   Show the diff of the mont recent revision.
<r>   Leave a review for the most recent revision.
"""

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
        self.commit_message = urwid.Text(u'')
        votes = mywid.Table([])
        self.left_column = urwid.Pile([('pack', change_info),
                                       ('pack', urwid.Divider()),
                                       ('pack', votes)])
        top = urwid.Columns([self.left_column, ('weight', 1, self.commit_message)])

        self.listbox = urwid.ListBox(urwid.SimpleFocusListWalker([]))
        self._w.contents.append((self.app.header, ('pack', 1)))
        self._w.contents.append((urwid.Divider(), ('pack', 1)))
        self._w.contents.append((self.listbox, ('weight', 1)))
        self._w.set_focus(2)

        self.listbox.body.append(top)
        self.listbox.body.append(urwid.Divider())
        self.listbox_patchset_start = len(self.listbox.body)

        self.refresh()

    def refresh(self):
        change_info = []
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            if change.reviewed:
                reviewed = ' (reviewed)'
            else:
                reviewed = ''
            self.title = 'Change %s%s' % (change.number, reviewed)
            self.app.status.update(title=self.title)
            self.project_key = change.project.key

            self.change_id_label.set_text(('change-data', change.change_id))
            self.owner_label.set_text(('change-data', change.owner))
            self.project_label.set_text(('change-data', change.project.name))
            self.branch_label.set_text(('change-data', change.branch))
            self.topic_label.set_text(('change-data', change.topic or ''))
            self.created_label.set_text(('change-data', str(change.created)))
            self.updated_label.set_text(('change-data', str(change.updated)))
            self.status_label.set_text(('change-data', change.status))
            self.commit_message.set_text(change.revisions[-1].message)

            categories = []
            approval_headers = [urwid.Text(('table-header', 'Name'))]
            for label in change.labels:
                if label.category in categories:
                    continue
                approval_headers.append(urwid.Text(('table-header', label.category)))
                categories.append(label.category)
            votes = mywid.Table(approval_headers)
            approvals_for_name = {}
            for approval in change.approvals:
                approvals = approvals_for_name.get(approval.name)
                if not approvals:
                    approvals = {}
                    row = []
                    row.append(urwid.Text(approval.name))
                    for i, category in enumerate(categories):
                        w = urwid.Text(u'')
                        approvals[category] = w
                        row.append(w)
                    approvals_for_name[approval.name] = approvals
                    votes.addRow(row)
                if str(approval.value) != '0':
                    approvals[approval.category].set_text(str(approval.value))
            votes = urwid.Padding(votes, width='pack')

            # TODO: update the existing table rather than replacing it
            # wholesale.  It will become more important if the table
            # gets selectable items (like clickable names).
            self.left_column.contents[2] = (votes, ('pack', None))

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
                # Revisions are extremely unlikely to be deleted, skip
                # that case.
                listbox_index += 1
            if len(self.listbox.body) == listbox_index:
                self.listbox.body.insert(listbox_index, urwid.Divider())
                listbox_index += 1
            for message in change.messages:
                row = self.message_rows.get(message.key)
                if not row:
                    row = ChangeMessageBox(message)
                    self.listbox.body.insert(listbox_index, row)
                    self.message_rows[message.key] = row
                # Messages are extremely unlikely to be deleted, skip
                # that case.
                listbox_index += 1

    def toggleReviewed(self):
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            change.reviewed = not change.reviewed

    def keypress(self, size, key):
        r = super(ChangeView, self).keypress(size, key)
        if r == 'R':
            self.toggleReviewed()
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
        return r

    def diff(self, revision_key):
        self.app.changeScreen(view_diff.DiffView(self.app, revision_key))
