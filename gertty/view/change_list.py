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

import urwid

from gertty import mywid
from gertty.view import change as view_change
import gertty.view

class ChangeRow(urwid.Button):
    change_focus_map = {None: 'focused',
                        'unreviewed-change': 'focused-unreviewed-change',
                        'reviewed-change': 'focused-reviewed-change',
                        }

    def selectable(self):
        return True

    def __init__(self, change, callback=None):
        super(ChangeRow, self).__init__('', on_press=callback, user_data=change.key)
        self.change_key = change.key
        self.subject = urwid.Text(u'', wrap='clip')
        self.number = urwid.Text(u'')
        cols = [(8, self.number), self.subject]
        self.columns = urwid.Columns(cols)
        self.row_style = urwid.AttrMap(self.columns, '')
        self._w = urwid.AttrMap(self.row_style, None, focus_map=self.change_focus_map)
        self.update(change)

    def update(self, change):
        if change.reviewed or change.hidden:
            style = 'reviewed-change'
        else:
            style = 'unreviewed-change'
        self.row_style.set_attr_map({None: style})
        self.subject.set_text(change.subject)
        self.number.set_text(str(change.number))
        del self.columns.contents[2:]
        for category in change.getCategories():
            v = change.getMaxForCategory(category)
            if v == 0:
                v = ''
            else:
                v = '%2i' % v
            self.columns.contents.append((urwid.Text(v), self.columns.options('given', 3)))

class ChangeListHeader(urwid.WidgetWrap):
    def __init__(self):
        cols = [(8, urwid.Text(u'Number')), urwid.Text(u'Subject')]
        super(ChangeListHeader, self).__init__(urwid.Columns(cols))

    def update(self, change):
        del self._w.contents[2:]
        for category in change.getCategories():
            self._w.contents.append((urwid.Text(' %s' % category[0]), self._w.options('given', 3)))

class ChangeListView(urwid.WidgetWrap):
    help = mywid.GLOBAL_HELP + """
This Screen
===========
<k>   Toggle the hidden flag for the currently selected change.
<l>   Toggle whether only unreviewed or all changes are displayed.
<v>   Toggle the reviewed flag for the currently selected change.
"""

    def __init__(self, app, project_key):
        super(ChangeListView, self).__init__(urwid.Pile([]))
        self.app = app
        self.project_key = project_key
        self.unreviewed = True
        self.change_rows = {}
        self.listbox = urwid.ListBox(urwid.SimpleFocusListWalker([]))
        self.header = ChangeListHeader()
        self.refresh()
        self._w.contents.append((app.header, ('pack', 1)))
        self._w.contents.append((urwid.Divider(), ('pack', 1)))
        self._w.contents.append((urwid.AttrWrap(self.header, 'table-header'), ('pack', 1)))
        self._w.contents.append((self.listbox, ('weight', 1)))
        self._w.set_focus(3)

    def refresh(self):
        unseen_keys = set(self.change_rows.keys())
        with self.app.db.getSession() as session:
            project = session.getProject(self.project_key)
            self.project_name = project.name
            if self.unreviewed:
                self.title = u'Unreviewed changes in %s' % project.name
                lst = project.unreviewed_changes
            else:
                self.title = u'Open changes in %s' % project.name
                lst = project.open_changes
            self.app.status.update(title=self.title)
            i = 0
            for change in lst:
                row = self.change_rows.get(change.key)
                if not row:
                    row = ChangeRow(change, self.onSelect)
                    self.listbox.body.insert(i, row)
                    self.change_rows[change.key] = row
                else:
                    row.update(change)
                    unseen_keys.remove(change.key)
                i += 1
            if project.changes:
                self.header.update(project.changes[0])
        for key in unseen_keys:
            row = self.change_rows[key]
            self.listbox.body.remove(row)
            del self.change_rows[key]

    def toggleReviewed(self, change_key):
        with self.app.db.getSession() as session:
            change = session.getChange(change_key)
            change.reviewed = not change.reviewed
            ret = change.reviewed
        return ret

    def toggleHidden(self, change_key):
        with self.app.db.getSession() as session:
            change = session.getChange(change_key)
            change.hidden = not change.hidden
            ret = change.hidden
        return ret

    def keypress(self, size, key):
        if key=='l':
            self.unreviewed = not self.unreviewed
            self.refresh()
            return None
        if key=='v':
            if not len(self.listbox.body):
                return None
            pos = self.listbox.focus_position
            reviewed = self.toggleReviewed(self.listbox.body[pos].change_key)
            self.refresh()
            return None
        if key=='k':
            if not len(self.listbox.body):
                return None
            pos = self.listbox.focus_position
            hidden = self.toggleHidden(self.listbox.body[pos].change_key)
            self.refresh()
            return None
        return super(ChangeListView, self).keypress(size, key)

    def onSelect(self, button, change_key):
        try:
            view = view_change.ChangeView(self.app, change_key)
            self.app.changeScreen(view)
        except gertty.view.DisplayError as e:
            self.app.error(e.message)
