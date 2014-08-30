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

from gertty import keymap
from gertty import mywid
from gertty import sync
from gertty.view import change as view_change
import gertty.view

class ChangeRow(urwid.Button):
    change_focus_map = {None: 'focused',
                        'unreviewed-change': 'focused-unreviewed-change',
                        'reviewed-change': 'focused-reviewed-change',
                        }

    def selectable(self):
        return True

    def __init__(self, change, project=False, owner=False, callback=None):
        super(ChangeRow, self).__init__('', on_press=callback, user_data=change.key)
        self.change_key = change.key
        self.subject = urwid.Text(u'', wrap='clip')
        self.number = urwid.Text(u'')
        self.project = urwid.Text(u'', wrap='clip')
        self.owner = urwid.Text(u'', wrap='clip')
        cols = [(6, self.number), ('weight', 4, self.subject)]
        if project:
            cols.append(('weight', 1, self.project))
        if owner:
            cols.append(('weight', 2, self.owner))
        self.num_columns = len(cols)
        self.columns = urwid.Columns(cols, dividechars=1)
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
        self.project.set_text(change.project.name.split('/')[-1])
        if change.owner:
            self.owner.set_text(change.owner.name)
        else:
            self.owner.set_text(u'')
        del self.columns.contents[self.num_columns:]
        for category in change.getCategories():
            v = change.getMaxForCategory(category)
            if v == 0:
                v = ''
            else:
                v = '%2i' % v
            self.columns.contents.append((urwid.Text(v), self.columns.options('given', 2)))

class ChangeListHeader(urwid.WidgetWrap):
    def __init__(self, project=False, owner=False):
        cols = [(6, urwid.Text(u'Number')), ('weight', 4, urwid.Text(u'Subject'))]
        if project:
            cols.append(('weight', 1, urwid.Text(u'Project')))
        if owner:
            cols.append(('weight', 2, urwid.Text(u'Owner')))
        self.num_columns = len(cols)
        super(ChangeListHeader, self).__init__(urwid.Columns(cols, dividechars=1))

    def update(self, change):
        del self._w.contents[self.num_columns:]
        for category in change.getCategories():
            self._w.contents.append((urwid.Text(' %s' % category[0]), self._w.options('given', 2)))

class ChangeListView(urwid.WidgetWrap):
    def help(self):
        key = self.app.config.keymap.formatKeys
        return [
            (key(keymap.TOGGLE_HIDDEN),
             "Toggle the hidden flag for the currently selected change"),
            (key(keymap.TOGGLE_LIST_REVIEWED),
             "Toggle whether only unreviewed or all changes are displayed"),
            (key(keymap.TOGGLE_REVIEWED),
             "Toggle the reviewed flag for the currently selected change"),
            (key(keymap.REFRESH),
             "Sync all projects")
            ]

    def __init__(self, app, query, query_desc=None, unreviewed=False):
        super(ChangeListView, self).__init__(urwid.Pile([]))
        self.app = app
        self.query = query
        self.query_desc = query_desc or query
        self.unreviewed = unreviewed
        self.change_rows = {}
        self.listbox = urwid.ListBox(urwid.SimpleFocusListWalker([]))
        self.display_owner = self.display_project = True
        if '_project_key' in query:
            self.display_project = False
        self.header = ChangeListHeader(self.display_project, self.display_owner)
        self.refresh()
        self._w.contents.append((app.header, ('pack', 1)))
        self._w.contents.append((urwid.Divider(), ('pack', 1)))
        self._w.contents.append((urwid.AttrWrap(self.header, 'table-header'), ('pack', 1)))
        self._w.contents.append((self.listbox, ('weight', 1)))
        self._w.set_focus(3)

    def refresh(self):
        unseen_keys = set(self.change_rows.keys())
        with self.app.db.getSession() as session:
            lst = session.getChanges(self.query, self.unreviewed)
            if self.unreviewed:
                self.title = u'Unreviewed changes in %s' % self.query_desc
            else:
                self.title = u'All changes in %s' % self.query_desc
            self.app.status.update(title=self.title)
            i = 0
            for change in lst:
                row = self.change_rows.get(change.key)
                if not row:
                    row = ChangeRow(change, self.display_project,
                                    self.display_owner, callback=self.onSelect)
                    self.listbox.body.insert(i, row)
                    self.change_rows[change.key] = row
                else:
                    row.update(change)
                    unseen_keys.remove(change.key)
                i += 1
            if lst:
                self.header.update(lst[0])
        for key in unseen_keys:
            row = self.change_rows[key]
            self.listbox.body.remove(row)
            del self.change_rows[key]

    def getNextChangeKey(self, change_key):
        row = self.change_rows.get(change_key)
        i = self.listbox.body.index(row)
        if i+1 >= len(self.listbox.body):
            return None
        row = self.listbox.body[i+1]
        return row.change_key

    def getPrevChangeKey(self, change_key):
        row = self.change_rows.get(change_key)
        i = self.listbox.body.index(row)
        if i <= 0:
            return None
        row = self.listbox.body[i-1]
        return row.change_key

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
        r = super(ChangeListView, self).keypress(size, key)
        commands = self.app.config.keymap.getCommands(r)
        if keymap.TOGGLE_LIST_REVIEWED in commands:
            self.unreviewed = not self.unreviewed
            self.refresh()
            return None
        if keymap.TOGGLE_REVIEWED in commands:
            if not len(self.listbox.body):
                return None
            pos = self.listbox.focus_position
            reviewed = self.toggleReviewed(self.listbox.body[pos].change_key)
            self.refresh()
            return None
        if keymap.TOGGLE_HIDDEN in commands:
            if not len(self.listbox.body):
                return None
            pos = self.listbox.focus_position
            hidden = self.toggleHidden(self.listbox.body[pos].change_key)
            self.refresh()
            return None
        if keymap.REFRESH in commands:
            self.app.sync.submitTask(
                sync.SyncSubscribedProjectsTask(sync.HIGH_PRIORITY))
            self.app.status.update()
            return None
        return key

    def onSelect(self, button, change_key):
        try:
            view = view_change.ChangeView(self.app, change_key)
            self.app.changeScreen(view)
        except gertty.view.DisplayError as e:
            self.app.error(e.message)
