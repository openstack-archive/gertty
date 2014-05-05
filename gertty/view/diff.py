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

from gertty import mywid
from gertty import gitrepo

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

class DiffCommentEdit(urwid.Columns):
    def __init__(self, context, old_key=None, new_key=None, old=u'', new=u''):
        super(DiffCommentEdit, self).__init__([])
        self.context = context
        # If we save a comment, the resulting key will be stored here
        self.old_key = old_key
        self.new_key = new_key
        self.old = urwid.Edit(edit_text=old, multiline=True)
        self.new = urwid.Edit(edit_text=new, multiline=True)
        self.contents.append((urwid.Text(u''), ('given', 4, False)))
        self.contents.append((urwid.AttrMap(self.old, 'draft-comment'), ('weight', 1, False)))
        self.contents.append((urwid.Text(u''), ('given', 4, False)))
        self.contents.append((urwid.AttrMap(self.new, 'draft-comment'), ('weight', 1, False)))
        self.focus_position = 3

    def keypress(self, size, key):
        r = super(DiffCommentEdit, self).keypress(size, key)
        if r in ['tab', 'shift tab']:
            if self.focus_position == 3:
                self.focus_position = 1
            else:
                self.focus_position = 3
            return None
        return r

class DiffComment(urwid.Columns):
    def __init__(self, context, old, new):
        super(DiffComment, self).__init__([])
        self.context = context
        oldt = urwid.Text(old)
        newt = urwid.Text(new)
        if old:
            oldt = urwid.AttrMap(oldt, 'comment')
        if new:
            newt = urwid.AttrMap(newt, 'comment')
        self.contents.append((urwid.Text(u''), ('given', 4, False)))
        self.contents.append((oldt, ('weight', 1, False)))
        self.contents.append((urwid.Text(u''), ('given', 4, False)))
        self.contents.append((newt, ('weight', 1, False)))

class DiffLine(urwid.Button):
    def selectable(self):
        return True

    def __init__(self, app, context, old, new, callback=None):
        super(DiffLine, self).__init__('', on_press=callback)
        self.context = context
        columns = []
        for (ln, action, line) in (old, new):
            if ln is None:
                ln = ''
            else:
                ln = str(ln)
            ln_col = urwid.Text(ln)
            ln_col.set_wrap_mode('clip')
            line_col = urwid.Text(line)
            line_col.set_wrap_mode('clip')
            if action == '':
                line_col = urwid.AttrMap(line_col, 'nonexistent')
            columns += [(4, ln_col), line_col]
        col = urwid.Columns(columns)
        map = {None: 'reversed',
               'added-line': 'reversed-added-line',
               'added-word': 'reversed-added-word',
               'removed-line': 'reversed-removed-line',
               'removed-word': 'reversed-removed-word',
               'nonexistent': 'reversed-nonexistent',
               }
        self._w = urwid.AttrMap(col, None, focus_map=map)

class DiffContextButton(urwid.WidgetWrap):
    def selectable(self):
        return True

    def __init__(self, view, diff, chunk):
        focus_map={'context-button':'selected-context-button'}
        buttons = [mywid.FixedButton(('context-button', "Expand previous 10"),
                                     on_press=self.prev),
                   mywid.FixedButton(('context-button',
                                      "Expand %s lines of context" % len(chunk.lines)),
                                     on_press=self.all),
                   mywid.FixedButton(('context-button', "Expand next 10"),
                                     on_press=self.next)]
        buttons = [('pack', urwid.AttrMap(b, None, focus_map=focus_map)) for b in buttons]
        buttons = urwid.Columns([urwid.Text('')] + buttons + [urwid.Text('')],
                                dividechars=4)
        buttons = urwid.AttrMap(buttons, 'context-button')
        super(DiffContextButton, self).__init__(buttons)
        self.view = view
        self.diff = diff
        self.chunk = chunk

    def prev(self, button):
        self.view.expandChunk(self.diff, self.chunk, from_start=10)

    def all(self, button):
        self.view.expandChunk(self.diff, self.chunk, expand_all=True)

    def next(self, button):
        self.view.expandChunk(self.diff, self.chunk, from_end=-10)

class DiffView(urwid.WidgetWrap):
    help = mywid.GLOBAL_HELP + """
This Screen
===========
<Enter> Add an inline comment.
"""

    def __init__(self, app, new_revision_key):
        super(DiffView, self).__init__(urwid.Pile([]))
        self.log = logging.getLogger('gertty.view.diff')
        self.app = app
        self.new_revision_key = new_revision_key
        with self.app.db.getSession() as session:
            revision = session.getRevision(new_revision_key)
            self.title = u'Diff of %s change %s patchset %s' % (
                revision.change.project.name,
                revision.change.number,
                revision.number)
            self.new_revision_num = revision.number
            self.change_key = revision.change.key
            self.project_name = revision.change.project.name
            self.parent = revision.parent
            self.commit = revision.commit
            comment_lists = {}
            for comment in revision.comments:
                if comment.parent:
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
                    message = [('comment-name', comment.name),
                               ('comment', u': '+comment.message)]
                comment_list.append((comment.key, message))
                comment_lists[key] = comment_list
        repo = self.app.getRepo(self.project_name)
        self._w.contents.append((app.header, ('pack', 1)))
        self._w.contents.append((urwid.Divider(), ('pack', 1)))
        lines = []  # The initial set of lines to display
        self.file_diffs = [{}, {}]  # Mapping of fn -> DiffFile object (old, new)
        # this is a list of files:
        for i, diff in enumerate(repo.diff(self.parent, self.commit)):
            if i > 0:
                lines.append(urwid.Text(''))
            self.file_diffs[gitrepo.OLD][diff.oldname] = diff
            self.file_diffs[gitrepo.NEW][diff.newname] = diff
            lines.append(urwid.Columns([
                        urwid.Text(('filename', diff.oldname)),
                        urwid.Text(('filename', diff.newname))]))
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

    def handleUndisplayedComments(self, comment_lists):
        # Handle comments that landed outside our default diff context
        import time
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

    def makeLines(self, diff, lines_to_add, comment_lists):
        lines = []
        for old, new in lines_to_add:
            context = LineContext(
                None, self.new_revision_key,
                None, self.new_revision_num,
                diff.oldname, diff.newname,
                old[0], new[0])
            lines.append(DiffLine(self.app, context, old, new,
                                  callback=self.onSelect))
            # see if there are any comments for this line
            key = 'old-%s-%s' % (old[0], diff.oldname)
            old_list = comment_lists.pop(key, [])
            key = 'new-%s-%s' % (new[0], diff.newname)
            new_list = comment_lists.pop(key, [])
            while old_list or new_list:
                old_comment_key = new_comment_key = None
                old_comment = new_comment = u''
                if old_list:
                    (old_comment_key, old_comment) = old_list.pop(0)
                if new_list:
                    (new_comment_key, new_comment) = new_list.pop(0)
                lines.append(DiffComment(context, old_comment, new_comment))
            # see if there are any draft comments for this line
            key = 'olddraft-%s-%s' % (old[0], diff.oldname)
            old_list = comment_lists.pop(key, [])
            key = 'newdraft-%s-%s' % (new[0], diff.newname)
            new_list = comment_lists.pop(key, [])
            while old_list or new_list:
                old_comment_key = new_comment_key = None
                old_comment = new_comment = u''
                if old_list:
                    (old_comment_key, old_comment) = old_list.pop(0)
                if new_list:
                    (new_comment_key, new_comment) = new_list.pop(0)
                lines.append(DiffCommentEdit(context,
                                             old_comment_key,
                                             new_comment_key,
                                             old_comment, new_comment))
        return lines

    def refresh(self):
        #TODO
        pass

    def keypress(self, size, key):
        old_focus = self.listbox.focus
        r = super(DiffView, self).keypress(size, key)
        new_focus = self.listbox.focus
        if old_focus != new_focus and isinstance(old_focus, DiffCommentEdit):
            self.cleanupEdit(old_focus)
        return r

    def mouse_event(self, size, event, button, x, y, focus):
        old_focus = self.listbox.focus
        r = super(DiffView, self).mouse_event(size, event, button, x, y, focus)
        new_focus = self.listbox.focus
        if old_focus != new_focus and isinstance(old_focus, DiffCommentEdit):
            self.cleanupEdit(old_focus)
        return r

    def onSelect(self, button):
        pos = self.listbox.focus_position
        e = DiffCommentEdit(self.listbox.body[pos].context)
        self.listbox.body.insert(pos+1, e)
        self.listbox.focus_position = pos+1

    def cleanupEdit(self, edit):
        if edit.old_key:
            self.deleteComment(edit.old_key)
            edit.old_key = None
        if edit.new_key:
            self.deleteComment(edit.new_key)
            edit.new_key = None
        old = edit.old.edit_text.strip()
        new = edit.new.edit_text.strip()
        if old or new:
            if old:
                edit.old_key = self.saveComment(
                    edit.context, old, new=False)
            if new:
                edit.new_key = self.saveComment(
                    edit.context, new, new=True)
        else:
            self.listbox.body.remove(edit)

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
            comment = revision.createComment(None, None,
                                             datetime.datetime.utcnow(),
                                             None, filename, parent,
                                             line_num, text, pending=True)
            key = comment.key
        return key
