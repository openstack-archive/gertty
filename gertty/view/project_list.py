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

import logging
import urwid

from gertty import keymap
from gertty import sync
from gertty.view import change_list as view_change_list
from gertty.view import mouse_scroll_decorator

class ProjectRow(urwid.Button):
    project_focus_map = {None: 'focused',
                         'unreviewed-project': 'focused-unreviewed-project',
                         'subscribed-project': 'focused-subscribed-project',
                         'unsubscribed-project': 'focused-unsubscribed-project',
                         }

    def selectable(self):
        return True

    def __init__(self, project, callback=None):
        super(ProjectRow, self).__init__('', on_press=callback,
                                         user_data=(project.key, project.name))
        self.project_key = project.key
        name = urwid.Text(project.name)
        name.set_wrap_mode('clip')
        self.unreviewed_changes = urwid.Text(u'', align=urwid.RIGHT)
        self.open_changes = urwid.Text(u'', align=urwid.RIGHT)
        col = urwid.Columns([
                name,
                ('fixed', 11, self.unreviewed_changes),
                ('fixed', 5, self.open_changes),
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
        self.unreviewed_changes.set_text('%i ' % len(project.unreviewed_changes))
        self.open_changes.set_text('%i ' % len(project.open_changes))

class ProjectListHeader(urwid.WidgetWrap):
    def __init__(self):
        cols = [urwid.Text(u'Project'),
                (11, urwid.Text(u'Unreviewed')),
                (5, urwid.Text(u'Open'))]
        super(ProjectListHeader, self).__init__(urwid.Columns(cols))

@mouse_scroll_decorator.ScrollByWheel
class ProjectListView(urwid.WidgetWrap):
    def help(self):
        key = self.app.config.keymap.formatKeys
        return [
            (key(keymap.TOGGLE_LIST_SUBSCRIBED),
             "Toggle whether only subscribed projects or all projects are listed"),
            (key(keymap.TOGGLE_LIST_REVIEWED),
             "Toggle listing of projects with unreviewed changes"),
            (key(keymap.TOGGLE_SUBSCRIBED),
             "Toggle the subscription flag for the currently selected project"),
            (key(keymap.REFRESH),
             "Sync subscribed projects")
            ]

    def __init__(self, app):
        super(ProjectListView, self).__init__(urwid.Pile([]))
        self.log = logging.getLogger('gertty.view.project_list')
        self.app = app
        self.unreviewed = True
        self.subscribed = True
        self.project_rows = {}
        self.listbox = urwid.ListBox(urwid.SimpleFocusListWalker([]))
        self.header = ProjectListHeader()
        self.refresh()
        self._w.contents.append((app.header, ('pack', 1)))
        self._w.contents.append((urwid.Divider(),('pack', 1)))
        self._w.contents.append((urwid.AttrWrap(self.header, 'table-header'), ('pack', 1)))
        self._w.contents.append((self.listbox, ('weight', 1)))
        self._w.set_focus(3)

    def interested(self, event):
        if not (isinstance(event, sync.ProjectAddedEvent)
                or
                isinstance(event, sync.ChangeAddedEvent)
                or
                (isinstance(event, sync.ChangeUpdatedEvent) and
                 (event.status_changed or event.review_flag_changed))):
            self.log.debug("Ignoring refresh project list due to event %s" % (event,))
            return False
        self.log.debug("Refreshing project list due to event %s" % (event,))
        return True

    def refresh(self):
        if self.subscribed:
            self.title = u'Subscribed projects'
            if self.unreviewed:
                self.title += u' with unreviewed changes'
        else:
            self.title = u'All projects'
        self.app.status.update(title=self.title)
        unseen_keys = set(self.project_rows.keys())
        with self.app.db.getSession() as session:
            i = 0
            for project in session.getProjects(
                    subscribed=self.subscribed, unreviewed=self.unreviewed):
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

    def onSelect(self, button, data):
        project_key, project_name = data
        self.app.changeScreen(view_change_list.ChangeListView(
                self.app,
                "_project_key:%s %s" % (project_key, self.app.config.project_change_list_query),
                project_name, project_key=project_key, unreviewed=True))

    def keypress(self, size, key):
        if not self.app.input_buffer:
            key = super(ProjectListView, self).keypress(size, key)
        keys = self.app.input_buffer + [key]
        commands = self.app.config.keymap.getCommands(keys)
        if not self.app.input_buffer and keymap.FURTHER_INPUT not in commands:
            self.app.clearInputBuffer()
        if keymap.TOGGLE_LIST_REVIEWED in commands:
            self.unreviewed = not self.unreviewed
            self.refresh()
            return None
        if keymap.TOGGLE_LIST_SUBSCRIBED in commands:
            self.subscribed = not self.subscribed
            self.refresh()
            return None
        if keymap.TOGGLE_SUBSCRIBED in commands:
            if not len(self.listbox.body):
                return None
            pos = self.listbox.focus_position
            project_key = self.listbox.body[pos].project_key
            subscribed = self.toggleSubscribed(project_key)
            self.refresh()
            if subscribed:
                self.app.sync.submitTask(sync.SyncProjectTask(project_key))
            return None
        if keymap.REFRESH in commands:
            self.app.sync.submitTask(
                sync.SyncSubscribedProjectsTask(sync.HIGH_PRIORITY))
            self.app.status.update()
            return None
        return key
