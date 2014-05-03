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

import mywid
import sync
import view.change_list

class ProjectRow(urwid.Button):
    project_focus_map = {None: 'reversed',
                         'unreviewed-project': 'reversed-unreviewed-project',
                         'subscribed-project': 'reversed-subscribed-project',
                         'unsubscribed-project': 'reversed-unsubscribed-project',
                         }

    def selectable(self):
        return True

    def __init__(self, project, callback=None):
        super(ProjectRow, self).__init__('', on_press=callback, user_data=project.key)
        self.project_key = project.key
        name = urwid.Text(u' '+project.name)
        name.set_wrap_mode('clip')
        self.unreviewed_changes = urwid.Text(u'')
        self.reviewed_changes = urwid.Text(u'')
        col = urwid.Columns([
                name,
                ('fixed', 4, self.unreviewed_changes),
                ('fixed', 4, self.reviewed_changes),
                ])
        self.row_style = urwid.AttrMap(col, '')
        self._w = urwid.AttrMap(self.row_style, None, focus_map=self.project_focus_map)
        self.update(project)

    def update(self, project):
        if project.subscribed:
            if len(project.unreviewed_changes) > 0:
                style = 'unreviewed-project'
            else:
                style = 'subscribed-project'
        else:
            style = 'unsubscribed-project'
        self.row_style.set_attr_map({None: style})
        self.unreviewed_changes.set_text(str(len(project.unreviewed_changes)))
        self.reviewed_changes.set_text(str(len(project.reviewed_changes)))

class ProjectListView(urwid.WidgetWrap):
    help = mywid.GLOBAL_HELP + """
This Screen
===========
<l>   Toggle whether only subscribed projects or all projects are listed.
<s>   Toggle the subscription flag for the currently selected project.
"""

    def __init__(self, app):
        super(ProjectListView, self).__init__(urwid.Pile([]))
        self.app = app
        self.subscribed = True
        self.project_rows = {}
        self.listbox = urwid.ListBox(urwid.SimpleFocusListWalker([]))
        self.refresh()
        self._w.contents.append((app.header, ('pack', 1)))
        self._w.contents.append((urwid.Divider(),('pack', 1)))
        self._w.contents.append((self.listbox, ('weight', 1)))
        self._w.set_focus(2)

    def refresh(self):
        if self.subscribed:
            self.title = u'Subscribed Projects'
        else:
            self.title = u'All Projects'
        self.app.status.update(title=self.title)
        unseen_keys = set(self.project_rows.keys())
        with self.app.db.getSession() as session:
            i = 0
            for project in session.getProjects(subscribed=self.subscribed):
                row = self.project_rows.get(project.key)
                if not row:
                    row = ProjectRow(project, self.onSelect)
                    self.listbox.body.insert(i, row)
                    self.project_rows[project.key] = row
                else:
                    row.update(project)
                    unseen_keys.remove(project.key)
                i += 1
        for key in unseen_keys:
            row = self.project_rows[key]
            self.listbox.body.remove(row)
            del self.project_rows[key]

    def toggleSubscribed(self, project_key):
        with self.app.db.getSession() as session:
            project = session.getProject(project_key)
            project.subscribed = not project.subscribed
            ret = project.subscribed
        return ret

    def onSelect(self, button, project_key):
        self.app.changeScreen(view.change_list.ChangeListView(self.app, project_key))

    def keypress(self, size, key):
        if key=='l':
            self.subscribed = not self.subscribed
            self.refresh()
            return None
        if key=='s':
            if not len(self.listbox.body):
                return None
            pos = self.listbox.focus_position
            project_key = self.listbox.body[pos].project_key
            subscribed = self.toggleSubscribed(project_key)
            self.refresh()
            if subscribed:
                self.app.sync.submitTask(sync.SyncProjectTask(project_key))
            return None
        return super(ProjectListView, self).keypress(size, key)


