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
import logging

import urwid

from gertty import keymap
from gertty import mywid
from gertty import gitrepo

class PatchsetDialog(urwid.WidgetWrap):
    signals = ['ok', 'cancel']

    def __init__(self, patchsets, old, new):
        button_widgets = []
        ok_button = mywid.FixedButton('OK')
        cancel_button = mywid.FixedButton('Cancel')
        urwid.connect_signal(ok_button, 'click',
                             lambda button:self._emit('ok'))
        urwid.connect_signal(cancel_button, 'click',
                             lambda button:self._emit('cancel'))
        button_widgets.append(('pack', ok_button))
        button_widgets.append(('pack', cancel_button))
        button_columns = urwid.Columns(button_widgets, dividechars=2)

        left = []
        right = []
        left.append(urwid.Text('Old'))
        right.append(urwid.Text('New'))
        self.old_buttons = []
        self.new_buttons = []
        self.patchset_keys = {}
        oldb = mywid.FixedRadioButton(self.old_buttons, 'Base',
                                      state=(old==None))
        left.append(oldb)
        right.append(urwid.Text(''))
        self.patchset_keys[oldb] = None
        for key, num in patchsets:
            oldb = mywid.FixedRadioButton(self.old_buttons, 'Patchset %d' % num,
                                          state=(old==key))
            newb = mywid.FixedRadioButton(self.new_buttons, 'Patchset %d' % num,
                                          state=(new==key))
            left.append(oldb)
            right.append(newb)
            self.patchset_keys[oldb] = key
            self.patchset_keys[newb] = key
        left = urwid.Pile(left)
        right = urwid.Pile(right)
        table  = urwid.Columns([left, right])
        rows = []
        rows.append(table)
        rows.append(urwid.Divider())
        rows.append(button_columns)
        pile = urwid.Pile(rows)
        fill = urwid.Filler(pile, valign='top')
        title = 'Patchsets'
        super(PatchsetDialog, self).__init__(urwid.LineBox(fill, title))

    def getSelected(self):
        old = new = None
        for b in self.old_buttons:
            if b.state:
                old = self.patchset_keys[b]
                break
        for b in self.new_buttons:
            if b.state:
                new = self.patchset_keys[b]
                break
        return old, new

class LineContext(object):
    def __init__(self, old_revision_key, new_revision_key,
                 old_revision_num, new_revision_num,
                 old_fn, new_fn, old_ln, new_ln):
        self.old_revision_key = old_revision_key
        self.new_revision_key = new_revision_key
        self.old_revision_num = old_revision_num
        self.new_revision_num = new_revision_num
        self.old_fn = old_fn
        self.new_fn = new_fn
        self.old_ln = old_ln
        self.new_ln = new_ln

class BaseDiffCommentEdit(urwid.Columns):
    pass

class BaseDiffComment(urwid.Columns):
    pass

class BaseDiffLine(urwid.Button):
    def selectable(self):
        return True

class BaseFileHeader(urwid.Button):
    def selectable(self):
        return True

class DiffContextButton(urwid.WidgetWrap):
    def selectable(self):
        return True

    def __init__(self, view, diff, chunk):
        focus_map={'context-button':'focused-context-button'}
        buttons = [mywid.FixedButton(('context-button', "Expand previous 10"),
                                     on_press=self.prev),
                   mywid.FixedButton(('context-button', "Expand"),
                                     on_press=self.all),
                   mywid.FixedButton(('context-button', "Expand next 10"),
                                     on_press=self.next)]
        self._buttons = buttons
        buttons = [('pack', urwid.AttrMap(b, None, focus_map=focus_map)) for b in buttons]
        buttons = urwid.Columns([urwid.Text('')] + buttons + [urwid.Text('')],
                                dividechars=4)
        buttons = urwid.AttrMap(buttons, 'context-button')
        super(DiffContextButton, self).__init__(buttons)
        self.view = view
        self.diff = diff
        self.chunk = chunk
        self.update()

    def update(self):
        self._buttons[1].set_label("Expand %s lines of context" %
                                   (len(self.chunk.lines)),)

    def prev(self, button):
        self.view.expandChunk(self.diff, self.chunk, from_start=10)

    def all(self, button):
        self.view.expandChunk(self.diff, self.chunk, expand_all=True)

    def next(self, button):
        self.view.expandChunk(self.diff, self.chunk, from_end=-10)

class BaseDiffView(urwid.WidgetWrap):
    def help(self):
        key = self.app.config.keymap.formatKeys
        return [
            (key(keymap.ACTIVATE),
             "Add an inline comment"),
            (key(keymap.SELECT_PATCHSETS),
             "Select old/new patchsets to diff"),
            ]

    def __init__(self, app, new_revision_key):
        super(BaseDiffView, self).__init__(urwid.Pile([]))
        self.log = logging.getLogger('gertty.view.diff')
        self.app = app
        self.old_revision_key = None  # Base
        self.new_revision_key = new_revision_key
        self._init()

    def _init(self):
        del self._w.contents[:]
        with self.app.db.getSession() as session:
            new_revision = session.getRevision(self.new_revision_key)
            if self.old_revision_key is not None:
                old_revision = session.getRevision(self.old_revision_key)
                self.old_revision_num = old_revision.number
                old_str = 'patchset %s' % self.old_revision_num
                self.base_commit = old_revision.commit
                old_comments = old_revision.comments
                show_old_commit = True
            else:
                old_revision = None
                self.old_revision_num = None
                old_str = 'base'
                self.base_commit = new_revision.parent
                old_comments = []
                show_old_commit = False
            self.title = u'Diff of %s change %s from %s to patchset %s' % (
                new_revision.change.project.name,
                new_revision.change.number,
                old_str, new_revision.number)
            self.new_revision_num = new_revision.number
            self.change_key = new_revision.change.key
            self.project_name = new_revision.change.project.name
            self.commit = new_revision.commit
            comment_lists = {}
            comment_filenames = set()
            for comment in new_revision.comments:
                if comment.parent:
                    if old_revision:  # we're not looking at the base
                        continue
                    key = 'old'
                else:
                    key = 'new'
                if comment.pending:
                    key += 'draft'
                key += '-' + str(comment.line)
                key += '-' + str(comment.file)
                comment_list = comment_lists.get(key, [])
                if comment.pending:
                    message = comment.message
                else:
                    message = [('comment-name', comment.author.name),
                               ('comment', u': '+comment.message)]
                comment_list.append((comment.key, message))
                comment_lists[key] = comment_list
                comment_filenames.add(comment.file)
            for comment in old_comments:
                if comment.parent:
                    continue
                key = 'old'
                if comment.pending:
                    key += 'draft'
                key += '-' + str(comment.line)
                key += '-' + str(comment.file)
                comment_list = comment_lists.get(key, [])
                if comment.pending:
                    message = comment.message
                else:
                    message = [('comment-name', comment.author.name),
                               ('comment', u': '+comment.message)]
                comment_list.append((comment.key, message))
                comment_lists[key] = comment_list
                comment_filenames.add(comment.file)
        repo = self.app.getRepo(self.project_name)
        self._w.contents.append((self.app.header, ('pack', 1)))
        self._w.contents.append((urwid.Divider(), ('pack', 1)))
        lines = []  # The initial set of lines to display
        self.file_diffs = [{}, {}]  # Mapping of fn -> DiffFile object (old, new)
        # this is a list of files:
        diffs = repo.diff(self.base_commit, self.commit,
                          show_old_commit=show_old_commit)
        for diff in diffs:
            comment_filenames.discard(diff.oldname)
            comment_filenames.discard(diff.newname)
        # There are comments referring to these files which do not
        # appear in the diff so we should create fake diff objects
        # that contain the full text.
        for filename in comment_filenames:
            diff = repo.getFile(self.base_commit, self.commit, filename)
            diffs.append(diff)
        for i, diff in enumerate(diffs):
            if i > 0:
                lines.append(urwid.Text(''))
            self.file_diffs[gitrepo.OLD][diff.oldname] = diff
            self.file_diffs[gitrepo.NEW][diff.newname] = diff
            lines.extend(self.makeFileHeader(diff, comment_lists))
            for chunk in diff.chunks:
                if chunk.context:
                    if not chunk.first:
                        lines += self.makeLines(diff, chunk.lines[:10], comment_lists)
                        del chunk.lines[:10]
                    button = DiffContextButton(self, diff, chunk)
                    chunk.button = button
                    lines.append(button)
                    if not chunk.last:
                        lines += self.makeLines(diff, chunk.lines[-10:], comment_lists)
                        del chunk.lines[-10:]
                    chunk.calcRange()
                    if not chunk.lines:
                        lines.remove(button)
                else:
                    lines += self.makeLines(diff, chunk.lines, comment_lists)
        listwalker = urwid.SimpleFocusListWalker(lines)
        self.listbox = urwid.ListBox(listwalker)
        self._w.contents.append((self.listbox, ('weight', 1)))
        self.old_focus = 2
        self.draft_comments = []
        self._w.set_focus(self.old_focus)
        self.handleUndisplayedComments(comment_lists)
        self.app.status.update(title=self.title)

    def handleUndisplayedComments(self, comment_lists):
        # Handle comments that landed outside our default diff context
        lastlen = 0
        while comment_lists:
            if len(comment_lists.keys()) == lastlen:
                self.log.error("Unable to display all comments: %s" % comment_lists)
                return
            lastlen = len(comment_lists.keys())
            key = comment_lists.keys()[0]
            kind, lineno, path = key.split('-', 2)
            lineno = int(lineno)
            if kind.startswith('old'):
                oldnew = gitrepo.OLD
            else:
                oldnew = gitrepo.NEW
            diff = self.file_diffs[oldnew][path]
            for chunk in diff.chunks:
                if (chunk.range[oldnew][gitrepo.START] <= lineno and
                    chunk.range[oldnew][gitrepo.END]   >= lineno):
                    i = chunk.indexOfLine(oldnew, lineno)
                    if i < (len(chunk.lines) / 2):
                        from_start = True
                    else:
                        from_start = False
                    if chunk.first and from_start:
                        from_start = False
                    if chunk.last and (not from_start):
                        from_start = True
                    if from_start:
                        self.expandChunk(diff, chunk, comment_lists, from_start=i+10)
                    else:
                        self.expandChunk(diff, chunk, comment_lists, from_end=i-10)
                    break

    def expandChunk(self, diff, chunk, comment_lists={}, from_start=None, from_end=None,
                    expand_all=None):
        self.log.debug("Expand chunk %s %s %s" % (chunk, from_start, from_end))
        add_lines = []
        if from_start is not None:
            index = self.listbox.body.index(chunk.button)
            add_lines = chunk.lines[:from_start]
            del chunk.lines[:from_start]
        if from_end is not None:
            index = self.listbox.body.index(chunk.button)+1
            add_lines = chunk.lines[from_end:]
            del chunk.lines[from_end:]
        if expand_all:
            index = self.listbox.body.index(chunk.button)
            add_lines = chunk.lines[:]
            del chunk.lines[:]
        if add_lines:
            lines = self.makeLines(diff, add_lines, comment_lists)
            self.listbox.body[index:index] = lines
        chunk.calcRange()
        if not chunk.lines:
            self.listbox.body.remove(chunk.button)
        else:
            chunk.button.update()

    def makeLines(self, diff, lines_to_add, comment_lists):
        raise NotImplementedError

    def makeFileHeader(self, diff, comment_lists):
        raise NotImplementedError

    def refresh(self):
        #TODO
        pass

    def keypress(self, size, key):
        old_focus = self.listbox.focus
        r = super(BaseDiffView, self).keypress(size, key)
        new_focus = self.listbox.focus
        commands = self.app.config.keymap.getCommands(r)
        if (isinstance(old_focus, BaseDiffCommentEdit) and
            (old_focus != new_focus or (keymap.PREV_SCREEN in commands))):
            self.cleanupEdit(old_focus)
        if keymap.SELECT_PATCHSETS in commands:
            self.openPatchsetDialog()
            return None
        return r

    def mouse_event(self, size, event, button, x, y, focus):
        old_focus = self.listbox.focus
        r = super(BaseDiffView, self).mouse_event(size, event, button, x, y, focus)
        new_focus = self.listbox.focus
        if old_focus != new_focus and isinstance(old_focus, BaseDiffCommentEdit):
            self.cleanupEdit(old_focus)
        return r

    def makeCommentEdit(self, edit):
        raise NotImplementedError

    def onSelect(self, button):
        pos = self.listbox.focus_position
        e = self.makeCommentEdit(self.listbox.body[pos])
        self.listbox.body.insert(pos+1, e)
        self.listbox.focus_position = pos+1

    def cleanupEdit(self, edit):
        raise NotImplementedError

    def deleteComment(self, comment_key):
        with self.app.db.getSession() as session:
            comment = session.getComment(comment_key)
            session.delete(comment)

    def saveComment(self, context, text, new=True):
        if (not new) and (not context.old_revision_num):
            parent = True
            revision_key = context.new_revision_key
        else:
            parent = False
            if new:
                revision_key = context.new_revision_key
            else:
                revision_key = context.old_revision_key
        if new:
            line_num = context.new_ln
            filename = context.new_fn
        else:
            line_num = context.old_ln
            filename = context.old_fn
        with self.app.db.getSession() as session:
            revision = session.getRevision(revision_key)
            account = session.getAccountByUsername(self.app.config.username)
            comment = revision.createComment(None, account, None,
                                             datetime.datetime.utcnow(),
                                             filename, parent,
                                             line_num, text, pending=True)
            key = comment.key
        return key

    def openPatchsetDialog(self):
        revisions = []
        with self.app.db.getSession() as session:
            change = session.getChange(self.change_key)
            for r in change.revisions:
                revisions.append((r.key, r.number))
        dialog = PatchsetDialog(revisions,
                                self.old_revision_key,
                                self.new_revision_key)
        urwid.connect_signal(dialog, 'cancel',
            lambda button: self.app.backScreen())
        urwid.connect_signal(dialog, 'ok',
            lambda button: self._openPatchsetDialog(dialog))
        self.app.popup(dialog, min_width=30, min_height=8)

    def _openPatchsetDialog(self, dialog):
        self.app.backScreen()
        self.old_revision_key, self.new_revision_key = dialog.getSelected()
        self._init()
