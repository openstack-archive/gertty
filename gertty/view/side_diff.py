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
from gertty.view.diff import *

class SideDiffCommentEdit(BaseDiffCommentEdit):
    def __init__(self, app, context, old_key=None, new_key=None, old=u'', new=u''):
        super(SideDiffCommentEdit, self).__init__([])
        self.app = app
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
        r = super(SideDiffCommentEdit, self).keypress(size, key)
        commands = self.app.config.keymap.getCommands(r)
        if ((keymap.NEXT_SELECTABLE in commands) or
            (keymap.PREV_SELECTABLE in commands)):
            if self.focus_position == 3:
                self.focus_position = 1
            else:
                self.focus_position = 3
            return None
        return r

class SideDiffComment(BaseDiffComment):
    def __init__(self, context, old, new):
        super(SideDiffComment, self).__init__([])
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

class SideDiffLine(BaseDiffLine):
    def __init__(self, app, context, old, new, callback=None):
        super(SideDiffLine, self).__init__('', on_press=callback)
        self.context = context
        columns = []
        for (ln, action, line) in (old, new):
            if ln is None:
                ln = ''
            else:
                ln = str(ln)
            ln_col = urwid.Text(('line-number', ln))
            ln_col.set_wrap_mode('clip')
            line_col = urwid.Text(line)
            if action == '':
                line_col = urwid.AttrMap(line_col, 'nonexistent')
            columns += [(4, ln_col), line_col]
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

class SideFileHeader(BaseFileHeader):
    def __init__(self, app, context, old, new, callback=None):
        super(SideFileHeader, self).__init__('', on_press=callback)
        self.context = context
        col = urwid.Columns([
                urwid.Text(('filename', old)),
                urwid.Text(('filename', new))])
        map = {None: 'focused-filename',
               'filename': 'focused-filename'}
        self._w = urwid.AttrMap(col, None, focus_map=map)


class SideDiffView(BaseDiffView):
    def makeLines(self, diff, lines_to_add, comment_lists):
        lines = []
        for old, new in lines_to_add:
            context = LineContext(
                self.old_revision_key, self.new_revision_key,
                self.old_revision_num, self.new_revision_num,
                diff.oldname, diff.newname,
                old[0], new[0])
            lines.append(SideDiffLine(self.app, context, old, new,
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
                lines.append(SideDiffComment(context, old_comment, new_comment))
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
                lines.append(SideDiffCommentEdit(self.app, context,
                                                 old_comment_key,
                                                 new_comment_key,
                                                 old_comment, new_comment))
        return lines

    def makeFileHeader(self, diff, comment_lists):
        context = LineContext(
            self.old_revision_key, self.new_revision_key,
            self.old_revision_num, self.new_revision_num,
            diff.oldname, diff.newname,
            None, None)
        lines = []
        lines.append(SideFileHeader(self.app, context, diff.oldname, diff.newname,
                                    callback=self.onSelect))

        # see if there are any comments for this file
        key = 'old-None-%s' % (diff.oldname,)
        old_list = comment_lists.pop(key, [])
        key = 'new-None-%s' % (diff.newname,)
        new_list = comment_lists.pop(key, [])
        while old_list or new_list:
            old_comment_key = new_comment_key = None
            old_comment = new_comment = u''
            if old_list:
                (old_comment_key, old_comment) = old_list.pop(0)
            if new_list:
                (new_comment_key, new_comment) = new_list.pop(0)
            lines.append(SideDiffComment(context, old_comment, new_comment))
        # see if there are any draft comments for this file
        key = 'olddraft-None-%s' % (diff.oldname,)
        old_list = comment_lists.pop(key, [])
        key = 'newdraft-None-%s' % (diff.newname,)
        new_list = comment_lists.pop(key, [])
        while old_list or new_list:
            old_comment_key = new_comment_key = None
            old_comment = new_comment = u''
            if old_list:
                (old_comment_key, old_comment) = old_list.pop(0)
            if new_list:
                (new_comment_key, new_comment) = new_list.pop(0)
            lines.append(SideDiffCommentEdit(self.app, context,
                                             old_comment_key,
                                             new_comment_key,
                                             old_comment, new_comment))
        return lines

    def makeCommentEdit(self, edit):
        return SideDiffCommentEdit(self.app, edit.context)

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
