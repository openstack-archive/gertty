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
import logging
import urlparse

import urwid

from gertty import gitrepo
from gertty import keymap
from gertty import mywid
from gertty import sync
from gertty.view import side_diff as view_side_diff
from gertty.view import unified_diff as view_unified_diff
from gertty.view import mouse_scroll_decorator
import gertty.view

class EditTopicDialog(mywid.ButtonDialog):
    signals = ['save', 'cancel']
    def __init__(self, app, topic):
        self.app = app
        save_button = mywid.FixedButton('Save')
        cancel_button = mywid.FixedButton('Cancel')
        urwid.connect_signal(save_button, 'click',
                             lambda button:self._emit('save'))
        urwid.connect_signal(cancel_button, 'click',
                             lambda button:self._emit('cancel'))
        super(EditTopicDialog, self).__init__("Edit Topic",
                                              "Edit the change topic.",
                                              entry_prompt="Topic: ",
                                              entry_text=topic,
                                              buttons=[save_button,
                                                       cancel_button],
                                              ring=app.ring)

    def keypress(self, size, key):
        if not self.app.input_buffer:
            key = super(EditTopicDialog, self).keypress(size, key)
        keys = self.app.input_buffer + [key]
        commands = self.app.config.keymap.getCommands(keys)
        if keymap.ACTIVATE in commands:
            self._emit('save')
            return None
        return key

class CherryPickDialog(urwid.WidgetWrap):
    signals = ['save', 'cancel']
    def __init__(self, app, change):
        save_button = mywid.FixedButton('Propose Change')
        cancel_button = mywid.FixedButton('Cancel')
        urwid.connect_signal(save_button, 'click',
                             lambda button:self._emit('save'))
        urwid.connect_signal(cancel_button, 'click',
                             lambda button:self._emit('cancel'))
        button_widgets = [('pack', save_button),
                          ('pack', cancel_button)]
        button_columns = urwid.Columns(button_widgets, dividechars=2)
        rows = []
        self.entry = mywid.MyEdit(edit_text=change.revisions[-1].message,
                                  multiline=True, ring=app.ring)
        self.branch_buttons = []
        rows.append(urwid.Text(u"Branch:"))
        for branch in change.project.branches:
            b = mywid.FixedRadioButton(self.branch_buttons, branch.name,
                                       state=(branch.name == change.branch))
            rows.append(b)
        rows.append(urwid.Divider())
        rows.append(urwid.Text(u"Commit message:"))
        rows.append(self.entry)
        rows.append(urwid.Divider())
        rows.append(button_columns)
        pile = urwid.Pile(rows)
        fill = urwid.Filler(pile, valign='top')
        super(CherryPickDialog, self).__init__(urwid.LineBox(fill,
                                                             'Propose Change to Branch'))

class ReviewDialog(urwid.WidgetWrap):
    signals = ['submit', 'save', 'cancel']
    def __init__(self, app, revision_key):
        self.revision_key = revision_key
        self.app = app
        save_button = mywid.FixedButton(u'Save')
        submit_button = mywid.FixedButton(u'Save and Submit')
        cancel_button = mywid.FixedButton(u'Cancel')
        urwid.connect_signal(save_button, 'click',
            lambda button:self._emit('save'))
        urwid.connect_signal(submit_button, 'click',
            lambda button:self._emit('submit'))
        urwid.connect_signal(cancel_button, 'click',
            lambda button:self._emit('cancel'))

        rows = []
        categories = []
        values = {}
        descriptions = {}
        self.button_groups = {}
        message = ''
        with self.app.db.getSession() as session:
            revision = session.getRevision(self.revision_key)
            change = revision.change
            buttons = [('pack', save_button)]
            if revision.can_submit:
                buttons.append(('pack', submit_button))
            buttons.append(('pack', cancel_button))
            buttons = urwid.Columns(buttons, dividechars=2)
            if revision == change.revisions[-1]:
                for label in change.labels:
                    d = descriptions.setdefault(label.category, {})
                    d[label.value] = label.description
                    vmin = d.setdefault('min', label.value)
                    if label.value < vmin:
                        d['min'] = label.value
                    vmax = d.setdefault('max', label.value)
                    if label.value > vmax:
                        d['max'] = label.value
                for label in change.permitted_labels:
                    if label.category not in categories:
                        categories.append(label.category)
                        values[label.category] = []
                    values[label.category].append(label.value)
                draft_approvals = {}
                for approval in change.draft_approvals:
                    draft_approvals[approval.category] = approval
                for category in categories:
                    rows.append(urwid.Text(category))
                    group = []
                    self.button_groups[category] = group
                    current = draft_approvals.get(category)
                    if current is None:
                        current = 0
                    else:
                        current = current.value
                    for value in sorted(values[category], reverse=True):
                        if value > 0:
                            strvalue = '+%s' % value
                        elif value == 0:
                            strvalue = ' 0'
                        else:
                            strvalue = str(value)
                        strvalue += '  ' + descriptions[category][value]
                        b = urwid.RadioButton(group, strvalue, state=(value == current))
                        b._value = value
                        if value > 0:
                            if value == descriptions[category]['max']:
                                b = urwid.AttrMap(b, 'max-label')
                            else:
                                b = urwid.AttrMap(b, 'positive-label')
                        elif value < 0:
                            if value == descriptions[category]['min']:
                                b = urwid.AttrMap(b, 'min-label')
                            else:
                                b = urwid.AttrMap(b, 'negative-label')
                        rows.append(b)
                    rows.append(urwid.Divider())
            m = revision.getPendingMessage()
            if not m:
                m = revision.getDraftMessage()
            if m:
                message = m.message
        self.message = mywid.MyEdit("Message: \n", edit_text=message,
                                    multiline=True, ring=app.ring)
        rows.append(self.message)
        rows.append(urwid.Divider())
        rows.append(buttons)
        pile = urwid.Pile(rows)
        fill = urwid.Filler(pile, valign='top')
        super(ReviewDialog, self).__init__(urwid.LineBox(fill, 'Review'))

    def getValues(self):
        approvals = {}
        for category, group in self.button_groups.items():
            for button in group:
                if button.state:
                    approvals[category] = button._value
        message = self.message.edit_text.strip()
        return (approvals, message)

    def keypress(self, size, key):
        if not self.app.input_buffer:
            key = super(ReviewDialog, self).keypress(size, key)
        keys = self.app.input_buffer + [key]
        commands = self.app.config.keymap.getCommands(keys)
        if keymap.PREV_SCREEN in commands:
            self._emit('cancel')
            return None
        return key

class ReviewButton(mywid.FixedButton):
    def __init__(self, revision_row):
        super(ReviewButton, self).__init__(('revision-button', u'Review'))
        self.revision_row = revision_row
        self.change_view = revision_row.change_view
        urwid.connect_signal(self, 'click',
            lambda button: self.openReview())

    def openReview(self):
        self.dialog = ReviewDialog(self.change_view.app,
                                   self.revision_row.revision_key)
        urwid.connect_signal(self.dialog, 'save',
            lambda button: self.closeReview(True, False))
        urwid.connect_signal(self.dialog, 'submit',
            lambda button: self.closeReview(True, True))
        urwid.connect_signal(self.dialog, 'cancel',
            lambda button: self.closeReview(False, False))
        self.change_view.app.popup(self.dialog,
                                   relative_width=50, relative_height=75,
                                   min_width=60, min_height=20)

    def closeReview(self, upload, submit):
        approvals, message = self.dialog.getValues()
        self.change_view.saveReview(self.revision_row.revision_key, approvals,
                                    message, upload, submit)
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
        self.can_submit = revision.can_submit
        self.title = mywid.TextButton(u'', on_press = self.expandContract)
        table = mywid.Table(columns=3)
        total_added = 0
        total_removed = 0
        for rfile in revision.files:
            if rfile.status is None:
                continue
            added = rfile.inserted or 0
            removed = rfile.deleted or 0
            total_added += added
            total_removed += removed
            table.addRow([urwid.Text(('filename', rfile.display_path), wrap='clip'),
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
        if self.can_submit:
            buttons.append(mywid.FixedButton(('revision-button', "Submit"),
                                             on_press=lambda x: self.change_view.doSubmitChange()))

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
        num_drafts = sum([len(f.draft_comments) for f in revision.files])
        if num_drafts:
            pending_message = revision.getPendingMessage()
            if not pending_message:
                line.append(('revision-drafts', ' (%s draft%s)' % (
                            num_drafts, num_drafts>1 and 's' or '')))
        num_comments = sum([len(f.comments) for f in revision.files]) - num_drafts
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
        self.app.localCheckoutCommit(self.project_name, self.commit_sha)

    def cherryPick(self, button):
        self.app.localCherryPickCommit(self.project_name, self.commit_sha)

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
        try:
            self.change_view.app.changeScreen(ChangeView(self.change_view.app, self.change_key))
        except gertty.view.DisplayError as e:
            self.change_view.app.error(e.message)

class ChangeMessageBox(mywid.HyperText):
    def __init__(self, app, message):
        super(ChangeMessageBox, self).__init__(u'')
        self.app = app
        self.refresh(message)

    def refresh(self, message):
        self.message_created = message.created
        created = self.app.time(message.created)
        lines = message.message.split('\n')
        if message.draft:
            lines.insert(0, '')
            lines.insert(0, 'Patch Set %s:' % (message.revision.number,))
        if message.author.username == self.app.config.username:
            name_style = 'change-message-own-name'
            header_style = 'change-message-own-header'
        else:
            name_style = 'change-message-name'
            header_style = 'change-message-header'
        text = [(name_style, message.author_name),
                (header_style, ': '+lines.pop(0)),
                (header_style,
                 created.strftime(' (%Y-%m-%d %H:%M:%S%z)'))]
        if message.draft and not message.pending:
            text.append(('change-message-draft', ' (draft)'))
        if lines and lines[-1]:
            lines.append('')
        comment_text = ['\n'.join(lines)]
        for commentlink in self.app.config.commentlinks:
            comment_text = commentlink.run(self.app, comment_text)
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

@mouse_scroll_decorator.ScrollByWheel
class ChangeView(urwid.WidgetWrap):
    def help(self):
        key = self.app.config.keymap.formatKeys
        ret = [
            (key(keymap.LOCAL_CHECKOUT),
             "Checkout the most recent revision into the local repo"),
            (key(keymap.DIFF),
             "Show the diff of the most recent revision"),
            (key(keymap.TOGGLE_HIDDEN),
             "Toggle the hidden flag for the current change"),
            (key(keymap.NEXT_CHANGE),
             "Go to the next change in the list"),
            (key(keymap.PREV_CHANGE),
             "Go to the previous change in the list"),
            (key(keymap.REVIEW),
             "Leave a review for the most recent revision"),
            (key(keymap.TOGGLE_HELD),
             "Toggle the held flag for the current change"),
            (key(keymap.TOGGLE_HIDDEN_COMMENTS),
             "Toggle display of hidden comments"),
            (key(keymap.SEARCH_RESULTS),
             "Back to the list of changes"),
            (key(keymap.TOGGLE_REVIEWED),
             "Toggle the reviewed flag for the current change"),
            (key(keymap.TOGGLE_STARRED),
             "Toggle the starred flag for the current change"),
            (key(keymap.LOCAL_CHERRY_PICK),
             "Cherry-pick the most recent revision onto the local repo"),
            (key(keymap.ABANDON_CHANGE),
             "Abandon this change"),
            (key(keymap.EDIT_COMMIT_MESSAGE),
             "Edit the commit message of this change"),
            (key(keymap.REBASE_CHANGE),
             "Rebase this change (remotely)"),
            (key(keymap.RESTORE_CHANGE),
             "Restore this change"),
            (key(keymap.REFRESH),
             "Refresh this change"),
            (key(keymap.EDIT_TOPIC),
             "Edit the topic of this change"),
            (key(keymap.SUBMIT_CHANGE),
             "Submit this change"),
            (key(keymap.CHERRY_PICK_CHANGE),
             "Propose this change to another branch"),
            ]

        for k in self.app.config.reviewkeys.values():
            action = ', '.join(['{category}:{value}'.format(**a) for a in k['approvals']])
            ret.append((keymap.formatKey(k['key']), action))

        return ret

    def __init__(self, app, change_key):
        super(ChangeView, self).__init__(urwid.Pile([]))
        self.log = logging.getLogger('gertty.view.change')
        self.app = app
        self.change_key = change_key
        self.revision_rows = {}
        self.message_rows = {}
        self.last_revision_key = None
        self.hide_comments = True
        self.change_id_label = mywid.TextButton(u'', on_press=self.searchChangeId)
        self.owner_label = mywid.TextButton(u'', on_press=self.searchOwner)
        self.project_label = mywid.TextButton(u'', on_press=self.searchProject)
        self.branch_label = urwid.Text(u'', wrap='clip')
        self.topic_label = mywid.TextButton(u'', on_press=self.searchTopic)
        self.created_label = urwid.Text(u'', wrap='clip')
        self.updated_label = urwid.Text(u'', wrap='clip')
        self.status_label = urwid.Text(u'', wrap='clip')
        self.permalink_label = mywid.TextButton(u'', on_press=self.openPermalink)
        change_info = []
        change_info_map={'change-data': 'focused-change-data'}
        for l, v in [("Change-Id", urwid.Padding(urwid.AttrMap(self.change_id_label, None,
                                                               focus_map=change_info_map),
                                                 width='pack')),
                     ("Owner", urwid.Padding(urwid.AttrMap(self.owner_label, None,
                                                           focus_map=change_info_map),
                                             width='pack')),
                     ("Project", urwid.Padding(urwid.AttrMap(self.project_label, None,
                                                           focus_map=change_info_map),
                                             width='pack')),
                     ("Branch", self.branch_label),
                     ("Topic", urwid.Padding(urwid.AttrMap(self.topic_label, None,
                                                           focus_map=change_info_map),
                                             width='pack')),
                     ("Created", self.created_label),
                     ("Updated", self.updated_label),
                     ("Status", self.status_label),
                     ("Permalink", urwid.Padding(urwid.AttrMap(self.permalink_label, None,
                                                               focus_map=change_info_map),
                                                 width='pack')),
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
        self.related_changes = urwid.Pile([self.depends_on, self.needed_by])
        self.results = mywid.HyperText(u'') # because it scrolls better than a table
        self.grid = mywid.MyGridFlow([change_info, self.commit_message, votes, self.results],
                                     cell_width=80, h_sep=2, v_sep=1, align='left')
        self.listbox = urwid.ListBox(urwid.SimpleFocusListWalker([]))
        self._w.contents.append((self.app.header, ('pack', 1)))
        self._w.contents.append((urwid.Divider(), ('pack', 1)))
        self._w.contents.append((self.listbox, ('weight', 1)))
        self._w.set_focus(2)

        self.listbox.body.append(self.grid)
        self.listbox.body.append(urwid.Divider())
        self.listbox.body.append(self.related_changes)
        self.listbox.body.append(urwid.Divider())
        self.listbox_patchset_start = len(self.listbox.body)

        self.checkGitRepo()
        self.refresh()
        self.listbox.set_focus(3)
        self.grid.set_focus(1)

    def checkGitRepo(self):
        missing_revisions = set()
        change_number = None
        change_id = None
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            change_number = change.number
            change_id = change.id
            repo = gitrepo.get_repo(change.project.name, self.app.config)
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

    def interested(self, event):
        if not ((isinstance(event, sync.ChangeAddedEvent) and
                 self.change_key in event.related_change_keys)
                or
                (isinstance(event, sync.ChangeUpdatedEvent) and
                 self.change_key in event.related_change_keys)):
            self.log.debug("Ignoring refresh change due to event %s" % (event,))
            return False
        self.log.debug("Refreshing change due to event %s" % (event,))
        return True

    def refresh(self):
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            self.topic = change.topic or ''
            self.pending_status_message = change.pending_status_message or ''
            reviewed = hidden = starred = held = ''
            if change.reviewed:
                reviewed = ' (reviewed)'
            if change.hidden:
                hidden = ' (hidden)'
            if change.starred:
                starred = '* '
            if change.held:
                held = ' (held)'
            self.title = '%sChange %s%s%s%s' % (starred, change.number, reviewed,
                                                hidden, held)
            self.app.status.update(title=self.title)
            self.project_key = change.project.key
            self.project_name = change.project.name
            self.change_rest_id = change.id
            self.change_id = change.change_id
            if change.owner:
                self.owner_email = change.owner.email
            else:
                self.owner_email = None

            self.change_id_label.text.set_text(('change-data', change.change_id))
            self.owner_label.text.set_text(('change-data', change.owner_name))
            self.project_label.text.set_text(('change-data', change.project.name))
            self.branch_label.set_text(('change-data', change.branch))
            self.topic_label.text.set_text(('change-data', self.topic))
            self.created_label.set_text(('change-data', str(self.app.time(change.created))))
            self.updated_label.set_text(('change-data', str(self.app.time(change.updated))))
            self.status_label.set_text(('change-data', change.status))
            self.permalink_url = urlparse.urljoin(self.app.config.url, str(change.number))
            self.permalink_label.text.set_text(('change-data', self.permalink_url))
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
            pending_message = change.revisions[-1].getPendingMessage()
            for approval in change.approvals:
                # Don't display draft approvals unless they are pending-upload
                if approval.draft and not pending_message:
                    continue
                approvals = approvals_for_name.get(approval.reviewer.name)
                if not approvals:
                    approvals = {}
                    row = []
                    if approval.reviewer.username == self.app.config.username:
                        style = 'reviewer-own-name'
                    else:
                        style = 'reviewer-name'
                    row.append(urwid.Text((style, approval.reviewer.name)))
                    for i, category in enumerate(categories):
                        w = urwid.Text(u'', align=urwid.CENTER)
                        approvals[category] = w
                        row.append(w)
                    approvals_for_name[approval.reviewer.name] = approvals
                    votes.addRow(row)
                if str(approval.value) != '0':
                    cat_min, cat_max = change.getMinMaxPermittedForCategory(approval.category)
                    if approval.value > 0:
                        val = '+%i' % approval.value
                        if approval.value == cat_max:
                            val = ('max-label', val)
                        else:
                            val = ('positive-label', val)
                    else:
                        val = '%i' % approval.value
                        if approval.value == cat_min:
                            val = ('min-label', val)
                        else:
                            val = ('negative-label', val)
                    approvals[approval.category].set_text(val)
            votes = urwid.Padding(votes, width='pack')

            # TODO: update the existing table rather than replacing it
            # wholesale.  It will become more important if the table
            # gets selectable items (like clickable names).
            self.grid.contents[2] = (votes, ('given', 80))

            self.refreshDependencies(session, change)

            repo = gitrepo.get_repo(change.project.name, self.app.config)
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
            # Get the set of messages that should be displayed
            display_messages = []
            result_systems = {}
            for message in change.messages:
                if (message.revision == change.revisions[-1] and
                    message.author and message.author.name):
                    for commentlink in self.app.config.commentlinks:
                        results = commentlink.getTestResults(self.app, message.message)
                        if results:
                            result_system = result_systems.get(message.author.name, {})
                            result_systems[message.author.name] = result_system
                            result_system.update(results)
                skip = False
                if self.hide_comments and message.author and message.author.name:
                    for regex in self.app.config.hide_comments:
                        if regex.match(message.author.name):
                            skip = True
                            break
                if not skip:
                    display_messages.append(message)
            # The set of message keys currently displayed
            unseen_keys = set(self.message_rows.keys())
            # Make sure all of the messages that should be displayed are
            for message in display_messages:
                row = self.message_rows.get(message.key)
                if not row:
                    box = ChangeMessageBox(self.app, message)
                    row = urwid.Padding(box, width=80)
                    self.listbox.body.insert(listbox_index, row)
                    self.message_rows[message.key] = row
                else:
                    unseen_keys.remove(message.key)
                    if message.created != row.original_widget.message_created:
                        row.original_widget.refresh(message)
                listbox_index += 1
            # Remove any messages that should not be displayed
            for key in unseen_keys:
                row = self.message_rows.get(key)
                self.listbox.body.remove(row)
                del self.message_rows[key]
                listbox_index -= 1
        self._updateTestResults(result_systems)

    def _updateTestResults(self, result_systems):
        text = []
        for system, results in result_systems.items():
            for job, result in results.items():
                text.append(result)
        if text:
            self.results.set_text(text)
        else:
            self.results.set_text('')

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
                row = (row, widget.options('pack'))
                widget.contents.insert(i, row)
                if not widget.selectable():
                    widget.set_focus(i)
                if not self.related_changes.selectable():
                    self.related_changes.set_focus(widget)
                widget_rows[key] = row
            else:
                row[0].original_widget.original_widget.set_label(subject)
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
            subject = parent.change.subject
            if parent != parent.change.revisions[-1]:
                subject += ' [OUTDATED]'
            parents[parent.change.key] = subject
        self._updateDependenciesWidget(parents,
                                       self.depends_on, self.depends_on_rows,
                                       header='Depends on:')

        # Handle needed-by
        children = {}
        children.update((r.change.key, r.change.subject)
                        for r in session.getRevisionsByParent([revision.commit for revision in change.revisions])
                        if (r.change.status != 'MERGED' and
                            r == r.change.revisions[-1]))
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

    def toggleStarred(self):
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            change.starred = not change.starred
            change.pending_starred = True
        self.app.sync.submitTask(
            sync.ChangeStarredTask(self.change_key, sync.HIGH_PRIORITY))

    def toggleHeld(self):
        return self.app.toggleHeldChange(self.change_key)

    def keypress(self, size, key):
        if not self.app.input_buffer:
            key = super(ChangeView, self).keypress(size, key)
        keys = self.app.input_buffer + [key]
        commands = self.app.config.keymap.getCommands(keys)
        if keymap.TOGGLE_REVIEWED in commands:
            self.toggleReviewed()
            self.refresh()
            return None
        if keymap.TOGGLE_HIDDEN in commands:
            self.toggleHidden()
            self.refresh()
            return None
        if keymap.TOGGLE_STARRED in commands:
            self.toggleStarred()
            self.refresh()
            return None
        if keymap.TOGGLE_HELD in commands:
            self.toggleHeld()
            self.refresh()
            return None
        if keymap.REVIEW in commands:
            row = self.revision_rows[self.last_revision_key]
            row.review_button.openReview()
            return None
        if keymap.DIFF in commands:
            row = self.revision_rows[self.last_revision_key]
            row.diff(None)
            return None
        if keymap.LOCAL_CHECKOUT in commands:
            row = self.revision_rows[self.last_revision_key]
            row.checkout(None)
            return None
        if keymap.LOCAL_CHERRY_PICK in commands:
            row = self.revision_rows[self.last_revision_key]
            row.cherryPick(None)
            return None
        if keymap.SEARCH_RESULTS in commands:
            widget = self.app.findChangeList()
            if widget:
                self.app.backScreen(widget)
            return None
        if ((keymap.NEXT_CHANGE in commands) or
            (keymap.PREV_CHANGE in commands)):
            widget = self.app.findChangeList()
            if widget:
                if keymap.NEXT_CHANGE in commands:
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
        if keymap.TOGGLE_HIDDEN_COMMENTS in commands:
            self.hide_comments = not self.hide_comments
            self.refresh()
            return None
        if keymap.ABANDON_CHANGE in commands:
            self.abandonChange()
            return None
        if keymap.EDIT_COMMIT_MESSAGE in commands:
            self.editCommitMessage()
            return None
        if keymap.REBASE_CHANGE in commands:
            self.rebaseChange()
            return None
        if keymap.RESTORE_CHANGE in commands:
            self.restoreChange()
            return None
        if keymap.REFRESH in commands:
            self.app.sync.submitTask(
                sync.SyncChangeTask(self.change_rest_id, priority=sync.HIGH_PRIORITY))
            self.app.status.update()
            return None
        if keymap.SUBMIT_CHANGE in commands:
            self.doSubmitChange()
            return None
        if keymap.EDIT_TOPIC in commands:
            self.editTopic()
            return None
        if keymap.CHERRY_PICK_CHANGE in commands:
            self.cherryPickChange()
            return None
        if key in self.app.config.reviewkeys:
            self.reviewKey(self.app.config.reviewkeys[key])
            return None
        return key

    def diff(self, revision_key):
        if self.app.config.diff_view == 'unified':
            screen = view_unified_diff.UnifiedDiffView(self.app, revision_key)
        else:
            screen = view_side_diff.SideDiffView(self.app, revision_key)
        self.app.changeScreen(screen)

    def abandonChange(self):
        dialog = mywid.TextEditDialog(u'Abandon Change', u'Abandon message:',
                                      u'Abandon Change',
                                      self.pending_status_message)
        urwid.connect_signal(dialog, 'cancel', self.app.backScreen)
        urwid.connect_signal(dialog, 'save', lambda button:
                                 self.doAbandonRestoreChange(dialog, 'ABANDONED'))
        self.app.popup(dialog)

    def restoreChange(self):
        dialog = mywid.TextEditDialog(u'Restore Change', u'Restore message:',
                                      u'Restore Change',
                                      self.pending_status_message)
        urwid.connect_signal(dialog, 'cancel', self.app.backScreen)
        urwid.connect_signal(dialog, 'save', lambda button:
                                 self.doAbandonRestoreChange(dialog, 'NEW'))
        self.app.popup(dialog)

    def doAbandonRestoreChange(self, dialog, state):
        change_key = None
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            change.status = state
            change.pending_status = True
            change.pending_status_message = dialog.entry.edit_text
            change_key = change.key
        self.app.sync.submitTask(
            sync.ChangeStatusTask(change_key, sync.HIGH_PRIORITY))
        self.app.backScreen()
        self.refresh()

    def editCommitMessage(self):
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            dialog = mywid.TextEditDialog(u'Edit Commit Message', u'Commit message:',
                                          u'Save', change.revisions[-1].message)
        urwid.connect_signal(dialog, 'cancel', self.app.backScreen)
        urwid.connect_signal(dialog, 'save', lambda button:
                                 self.doEditCommitMessage(dialog))
        self.app.popup(dialog,
                       relative_width=50, relative_height=75,
                       min_width=60, min_height=20)

    def doEditCommitMessage(self, dialog):
        revision_key = None
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            revision = change.revisions[-1]
            revision.message = dialog.entry.edit_text
            revision.pending_message = True
            revision_key = revision.key
        self.app.sync.submitTask(
            sync.ChangeCommitMessageTask(revision_key, sync.HIGH_PRIORITY))
        self.app.backScreen()
        self.refresh()

    def rebaseChange(self):
        dialog = mywid.YesNoDialog(u'Rebase Change',
                                   u'Perform a remote rebase of this change?')
        urwid.connect_signal(dialog, 'no', self.app.backScreen)
        urwid.connect_signal(dialog, 'yes', self.doRebaseChange)
        self.app.popup(dialog)

    def doRebaseChange(self, button=None):
        change_key = None
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            change.pending_rebase = True
            change_key = change.key
        self.app.sync.submitTask(
            sync.RebaseChangeTask(change_key, sync.HIGH_PRIORITY))
        self.app.backScreen()
        self.refresh()

    def cherryPickChange(self):
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            dialog = CherryPickDialog(self.app, change)
        urwid.connect_signal(dialog, 'cancel', self.app.backScreen)
        urwid.connect_signal(dialog, 'save', lambda button:
                                 self.doCherryPickChange(dialog))
        self.app.popup(dialog,
                       relative_width=50, relative_height=75,
                       min_width=60, min_height=20)


    def doCherryPickChange(self, dialog):
        cp_key = None
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            branch = None
            for button in dialog.branch_buttons:
                if button.state:
                    branch = button.get_label()
            message = dialog.entry.edit_text
            self.app.log.debug("Creating pending cherry-pick of %s to %s" %
                               (change.revisions[-1].commit, branch))
            cp = change.revisions[-1].createPendingCherryPick(branch, message)
            cp_key = cp.key
        self.app.sync.submitTask(
            sync.SendCherryPickTask(cp_key, sync.HIGH_PRIORITY))
        self.app.backScreen()
        self.refresh()

    def doSubmitChange(self):
        change_key = None
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            change.status = 'SUBMITTED'
            change.pending_status = True
            change.pending_status_message = None
            change_key = change.key
        self.app.sync.submitTask(
            sync.ChangeStatusTask(change_key, sync.HIGH_PRIORITY))
        self.refresh()

    def editTopic(self):
        dialog = EditTopicDialog(self.app, self.topic)
        urwid.connect_signal(dialog, 'save',
            lambda button: self.closeEditTopic(dialog, True))
        urwid.connect_signal(dialog, 'cancel',
            lambda button: self.closeEditTopic(dialog, False))
        self.app.popup(dialog)

    def closeEditTopic(self, dialog, save):
        if save:
            change_key = None
            with self.app.db.getSession() as session:
                change = session.getChange(self.change_key)
                change.topic = dialog.entry.edit_text
                change.pending_topic = True
                change_key = change.key
            self.app.sync.submitTask(
                sync.SetTopicTask(change_key, sync.HIGH_PRIORITY))
        self.app.backScreen()
        self.refresh()

    def openPermalink(self, widget):
        self.app.openURL(self.permalink_url)

    def searchChangeId(self, widget):
        self.app.doSearch("status:open change:%s" % (self.change_id,))

    def searchOwner(self, widget):
        if self.owner_email:
            self.app.doSearch("status:open owner:%s" % (self.owner_email,))

    def searchProject(self, widget):
        self.app.doSearch("status:open project:%s" % (self.project_name,))

    def searchTopic(self, widget):
        if self.topic:
            self.app.doSearch("status:open topic:%s" % (self.topic,))

    def reviewKey(self, reviewkey):
        approvals = {}
        for a in reviewkey['approvals']:
            approvals[a['category']] = a['value']
        self.app.log.debug("Reviewkey %s with approvals %s" %
                           (reviewkey['key'], approvals))
        row = self.revision_rows[self.last_revision_key]
        submit = reviewkey.get('submit', False)
        self.saveReview(row.revision_key, approvals, '', True, submit)

    def saveReview(self, revision_key, approvals, message, upload, submit):
        message_keys = self.app.saveReviews([revision_key], approvals,
                                            message, upload, submit)
        if upload:
            for message_key in message_keys:
                self.app.sync.submitTask(
                    sync.UploadReviewTask(message_key, sync.HIGH_PRIORITY))
        self.refresh()
