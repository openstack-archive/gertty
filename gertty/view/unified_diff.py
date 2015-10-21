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

import urwid

from gertty import gitrepo
from gertty import mywid
from gertty.view.diff import BaseDiffCommentEdit, BaseDiffComment, BaseDiffLine
from gertty.view.diff import BaseFileHeader, BaseFileReminder, BaseDiffView

LN_COL_WIDTH = 5

class UnifiedDiffCommentEdit(BaseDiffCommentEdit):
    def __init__(self, app, context, oldnew, key=None, comment=u''):
        super(UnifiedDiffCommentEdit, self).__init__([])
        self.context = context
        self.oldnew = oldnew
        # If we save a comment, the resulting key will be stored here
        self.key = key
        self.comment = mywid.MyEdit(edit_text=comment, multiline=True,
                                    ring=app.ring)
        self.contents.append((urwid.Text(u''), ('given', 8, False)))
        self.contents.append((urwid.AttrMap(self.comment, 'draft-comment'),
                              ('weight', 1, False)))
        self.focus_position = 1

class UnifiedDiffComment(BaseDiffComment):
    def __init__(self, context, oldnew, comment):
        super(UnifiedDiffComment, self).__init__([])
        self.context = context
        text = urwid.AttrMap(urwid.Text(comment), 'comment')
        self.contents.append((urwid.Text(u''), ('given', 8, False)))
        self.contents.append((text, ('weight', 1, False)))

class UnifiedDiffLine(BaseDiffLine):
    def __init__(self, app, context, oldnew, old, new, callback=None):
        super(UnifiedDiffLine, self).__init__('', on_press=callback)
        self.context = context
        self.oldnew = oldnew
        (old_ln, old_action, old_line) = old
        (new_ln, new_action, new_line) = new
        if old_ln is None:
            old_ln = ''
        else:
            old_ln = '%*i' % (LN_COL_WIDTH-1, old_ln)
        if new_ln is None:
            new_ln = ''
        else:
            new_ln = '%*i' % (LN_COL_WIDTH-1, new_ln)
        old_ln_col = urwid.Text(('line-number', old_ln))
        old_ln_col.set_wrap_mode('clip')
        new_ln_col = urwid.Text(('line-number', new_ln))
        new_ln_col.set_wrap_mode('clip')
        if oldnew == gitrepo.OLD:
            action = old_action
            line = old_line
            columns = [(LN_COL_WIDTH, old_ln_col), (LN_COL_WIDTH, urwid.Text(u''))]
        elif oldnew == gitrepo.NEW:
            action = new_action
            line = new_line
            columns = [(LN_COL_WIDTH, urwid.Text(u'')), (LN_COL_WIDTH, new_ln_col)]
        if new_action == ' ':
            columns = [(LN_COL_WIDTH, old_ln_col), (LN_COL_WIDTH, new_ln_col)]
        line_col = mywid.SearchableText(line)
        self.text_widget = line_col
        if action == '':
            line_col = urwid.AttrMap(line_col, 'nonexistent')
        columns += [line_col]
        col = urwid.Columns(columns)
        map = {None: 'focused',
               'added-line': 'focused-added-line',
               'added-word': 'focused-added-word',
               'removed-line': 'focused-removed-line',
               'removed-word': 'focused-removed-word',
               'nonexistent': 'focused-nonexistent',
               'line-number': 'focused-line-number',
               }
        self._w = urwid.AttrMap(col, None, focus_map=map)

    def search(self, search, attribute):
        return self.text_widget.search(search, attribute)

class UnifiedFileHeader(BaseFileHeader):
    def __init__(self, app, context, oldnew, old, new, callback=None):
        super(UnifiedFileHeader, self).__init__('', on_press=callback)
        self.context = context
        self.oldnew = oldnew
        if oldnew == gitrepo.OLD:
            col = urwid.Columns([
                    urwid.Text(('filename', old))])
        elif oldnew == gitrepo.NEW:
            col = urwid.Columns([
                    (LN_COL_WIDTH, urwid.Text(u'')),
                    urwid.Text(('filename', new))])
        map = {None: 'focused-filename',
               'filename': 'focused-filename'}
        self._w = urwid.AttrMap(col, None, focus_map=map)

class UnifiedFileReminder(BaseFileReminder):
    def __init__(self):
        self.old_text = urwid.Text(('filename', ''))
        self.new_text = urwid.Text(('filename', ''))
        self.col = urwid.Columns([('pack', self.old_text),
                                  ('pack', self.new_text),
                                  urwid.Text(u'')], dividechars=2)
        super(UnifiedFileReminder, self).__init__(self.col)

    def set(self, old, new):
        self.old_text.set_text(('filename', old))
        self.new_text.set_text(('filename', new))
        self.col._invalidate()

class UnifiedDiffView(BaseDiffView):
    def makeLines(self, diff, lines_to_add, comment_lists):
        lines = []
        for old, new in lines_to_add:
            context = self.makeContext(diff, old[0], new[0])
            if context.old_ln is not None:
                lines.append(UnifiedDiffLine(self.app, context, gitrepo.OLD, old, new,
                                             callback=self.onSelect))
            # see if there are any comments for this line
            key = 'old-%s-%s' % (old[0], diff.oldname)
            old_list = comment_lists.pop(key, [])
            while old_list:
                (old_comment_key, old_comment) = old_list.pop(0)
                lines.append(UnifiedDiffComment(context, gitrepo.OLD, old_comment))
            # see if there are any draft comments for this line
            key = 'olddraft-%s-%s' % (old[0], diff.oldname)
            old_list = comment_lists.pop(key, [])
            while old_list:
                (old_comment_key, old_comment) = old_list.pop(0)
                lines.append(UnifiedDiffCommentEdit(self.app,
                                                    context,
                                                    gitrepo.OLD,
                                                    old_comment_key,
                                                    old_comment))
            # new line
            if context.new_ln is not None and new[1] != ' ':
                lines.append(UnifiedDiffLine(self.app, context, gitrepo.NEW, old, new,
                                             callback=self.onSelect))
            # see if there are any comments for this line
            key = 'new-%s-%s' % (new[0], diff.newname)
            new_list = comment_lists.pop(key, [])
            while new_list:
                (new_comment_key, new_comment) = new_list.pop(0)
                lines.append(UnifiedDiffComment(context, gitrepo.NEW, new_comment))
            # see if there are any draft comments for this line
            key = 'newdraft-%s-%s' % (new[0], diff.newname)
            new_list = comment_lists.pop(key, [])
            while new_list:
                (new_comment_key, new_comment) = new_list.pop(0)
                lines.append(UnifiedDiffCommentEdit(self.app,
                                                    context,
                                                    gitrepo.NEW,
                                                    new_comment_key,
                                                    new_comment))
        return lines

    def makeFileReminder(self):
        return UnifiedFileReminder()

    def makeFileHeader(self, diff, comment_lists):
        context = self.makeContext(diff, None, None, header=True)
        lines = []
        lines.append(UnifiedFileHeader(self.app, context, gitrepo.OLD,
                                       diff.oldname, diff.newname,
                                       callback=self.onSelect))
        # see if there are any comments for this file
        key = 'old-None-%s' % (diff.oldname,)
        old_list = comment_lists.pop(key, [])
        while old_list:
            (old_comment_key, old_comment) = old_list.pop(0)
            lines.append(UnifiedDiffComment(context, gitrepo.OLD, old_comment))
        # see if there are any draft comments for this file
        key = 'olddraft-None-%s' % (diff.oldname,)
        old_list = comment_lists.pop(key, [])
        while old_list:
            (old_comment_key, old_comment) = old_list.pop(0)
            lines.append(UnifiedDiffCommentEdit(self.app,
                                                context,
                                                gitrepo.OLD,
                                                old_comment_key,
                                                old_comment))
        # new line
        lines.append(UnifiedFileHeader(self.app, context, gitrepo.NEW,
                                       diff.oldname, diff.newname,
                                       callback=self.onSelect))

        # see if there are any comments for this file
        key = 'new-None-%s' % (diff.newname,)
        new_list = comment_lists.pop(key, [])
        while new_list:
            (new_comment_key, new_comment) = new_list.pop(0)
            lines.append(UnifiedDiffComment(context, gitrepo.NEW, new_comment))
        # see if there are any draft comments for this file
        key = 'newdraft-None-%s' % (diff.newname,)
        new_list = comment_lists.pop(key, [])
        while new_list:
            (new_comment_key, new_comment) = new_list.pop(0)
            lines.append(UnifiedDiffCommentEdit(self.app,
                                                context,
                                                gitrepo.NEW,
                                                new_comment_key,
                                                new_comment))
        return lines

    def makeCommentEdit(self, edit):
        return UnifiedDiffCommentEdit(self.app,
                                      edit.context,
                                      edit.oldnew)

    def cleanupEdit(self, edit):
        if edit.key:
            self.deleteComment(edit.key)
            edit.key = None
        comment = edit.comment.edit_text.strip()
        if comment:
            new = False
            if edit.oldnew == gitrepo.NEW:
                new = True
            edit.key = self.saveComment(
                edit.context, comment, new=new)
        else:
            self.listbox.body.remove(edit)
