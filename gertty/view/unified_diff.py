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

import urwid

from gertty import mywid
from gertty import gitrepo
from gertty.view.diff import *

class UnifiedDiffCommentEdit(BaseDiffCommentEdit):
    def __init__(self, context, oldnew, key=None, comment=u''):
        super(UnifiedDiffCommentEdit, self).__init__([])
        self.context = context
        self.oldnew = oldnew
        # If we save a comment, the resulting key will be stored here
        self.key = key
        self.comment = urwid.Edit(edit_text=comment, multiline=True)
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
            old_ln = str(old_ln)
        if new_ln is None:
            new_ln = ''
        else:
            new_ln = str(new_ln)
        old_ln_col = urwid.Text(('line-number', old_ln))
        old_ln_col.set_wrap_mode('clip')
        new_ln_col = urwid.Text(('line-number', new_ln))
        new_ln_col.set_wrap_mode('clip')
        if oldnew == gitrepo.OLD:
            action = old_action
            line = old_line
            columns = [(4, old_ln_col), (4, urwid.Text(u''))]
        elif oldnew == gitrepo.NEW:
            action = new_action
            line = new_line
            columns = [(4, urwid.Text(u'')), (4, new_ln_col)]
        if new_action == ' ':
            columns = [(4, old_ln_col), (4, new_ln_col)]
        line_col = urwid.Text(line)
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
                    (4, urwid.Text(u'')),
                    urwid.Text(('filename', new))])
        map = {None: 'focused-filename',
               'filename': 'focused-filename'}
        self._w = urwid.AttrMap(col, None, focus_map=map)

class UnifiedDiffView(BaseDiffView):
    def makeLines(self, diff, lines_to_add, comment_lists):
        lines = []
        for old, new in lines_to_add:
            context = LineContext(
                self.old_revision_key, self.new_revision_key,
                self.old_revision_num, self.new_revision_num,
                diff.oldname, diff.newname,
                old[0], new[0])
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
                lines.append(UnifiedDiffCommentEdit(context,
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
                lines.append(UnifiedDiffCommentEdit(context,
                                                    gitrepo.NEW,
                                                    new_comment_key,
                                                    new_comment))
        return lines

    def makeFileHeader(self, diff, comment_lists):
        context = LineContext(
            self.old_revision_key, self.new_revision_key,
            self.old_revision_num, self.new_revision_num,
            diff.oldname, diff.newname,
            None, None)
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
            lines.append(UnifiedDiffCommentEdit(context,
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
            lines.append(UnifiedDiffCommentEdit(context,
                                                gitrepo.NEW,
                                                new_comment_key,
                                                new_comment))
        return lines

    def makeCommentEdit(self, edit):
        return UnifiedDiffCommentEdit(edit.context,
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
