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
from gertty import mywid
from gertty import sync
from gertty.view import change_list as view_change_list
from gertty.view import mouse_scroll_decorator

class TopicSelectDialog(urwid.WidgetWrap):
    signals = ['ok', 'cancel']

    def __init__(self, title, topics):
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

        self.topic_buttons = []
        self.topic_keys = {}
        rows = []
        for key, name in topics:
            button = mywid.FixedRadioButton(self.topic_buttons, name)
            self.topic_keys[button] = key
            rows.append(button)

        rows.append(urwid.Divider())
        rows.append(button_columns)
        pile = urwid.Pile(rows)
        fill = urwid.Filler(pile, valign='top')
        super(TopicSelectDialog, self).__init__(urwid.LineBox(fill, title))

    def getSelected(self):
        for b in self.topic_buttons:
            if b.state:
                return self.topic_keys[b]
        return None

class ProjectRow(urwid.Button):
    project_focus_map = {None: 'focused',
                         'unreviewed-project': 'focused-unreviewed-project',
                         'subscribed-project': 'focused-subscribed-project',
                         'unsubscribed-project': 'focused-unsubscribed-project',
                         'marked-project': 'focused-marked-project',
    }

    def selectable(self):
        return True

    def _setName(self, name, indent):
        self.project_name = name
        name = indent+name
        if self.mark:
            name = '%'+name
        else:
            name = ' '+name
        self.name.set_text(name)

    def __init__(self, app, project, topic, callback=None):
        super(ProjectRow, self).__init__('', on_press=callback,
                                         user_data=(project.key, project.name))
        self.app = app
        self.mark = False
        self._style = None
        self.project_key = project.key
        if topic:
            self.topic_key = topic.key
            self.indent = '  '
        else:
            self.topic_key = None
            self.indent = ''
        self.project_name = project.name
        self.name = mywid.SearchableText('')
        self._setName(project.name, self.indent)
        self.name.set_wrap_mode('clip')
        self.unreviewed_changes = urwid.Text(u'', align=urwid.RIGHT)
        self.open_changes = urwid.Text(u'', align=urwid.RIGHT)
        col = urwid.Columns([
                self.name,
                ('fixed', 11, self.unreviewed_changes),
                ('fixed', 5, self.open_changes),
                ])
        self.row_style = urwid.AttrMap(col, '')
        self._w = urwid.AttrMap(self.row_style, None, focus_map=self.project_focus_map)
        self.update(project)

    def search(self, search, attribute):
        return self.name.search(search, attribute)

    def update(self, project):
        cache = self.app.project_cache.get(project)
        if project.subscribed:
            if cache['unreviewed_changes'] > 0:
                style = 'unreviewed-project'
            else:
                style = 'subscribed-project'
        else:
            style = 'unsubscribed-project'
        self._style = style
        if self.mark:
            style = 'marked-project'
        self.row_style.set_attr_map({None: style})
        self.unreviewed_changes.set_text('%i ' % cache['unreviewed_changes'])
        self.open_changes.set_text('%i ' % cache['open_changes'])

    def toggleMark(self):
        self.mark = not self.mark
        if self.mark:
            style = 'marked-project'
        else:
            style = self._style
        self.row_style.set_attr_map({None: style})
        self._setName(self.project_name, self.indent)

class TopicRow(urwid.Button):
    project_focus_map = {None: 'focused',
                         'subscribed-project': 'focused-subscribed-project',
                         'marked-project': 'focused-marked-project',
    }

    def selectable(self):
        return True

    def _setName(self, name):
        self.topic_name = name
        name = '[[ '+name+' ]]'
        if self.mark:
            name = '%'+name
        else:
            name = ' '+name
        self.name.set_text(name)

    def __init__(self, topic, callback=None):
        super(TopicRow, self).__init__('', on_press=callback,
                                       user_data=(topic.key, topic.name))
        self.mark = False
        self._style = None
        self.topic_key = topic.key
        self.name = urwid.Text('')
        self._setName(topic.name)
        self.name.set_wrap_mode('clip')
        self.unreviewed_changes = urwid.Text(u'', align=urwid.RIGHT)
        self.open_changes = urwid.Text(u'', align=urwid.RIGHT)
        col = urwid.Columns([
                self.name,
                ('fixed', 11, self.unreviewed_changes),
                ('fixed', 5, self.open_changes),
                ])
        self.row_style = urwid.AttrMap(col, '')
        self._w = urwid.AttrMap(self.row_style, None, focus_map=self.project_focus_map)
        self._style = 'subscribed-project'
        self.row_style.set_attr_map({None: self._style})
        self.update(topic)

    def update(self, topic, unreviewed_changes=None, open_changes=None):
        self._setName(topic.name)
        if unreviewed_changes is None:
            self.unreviewed_changes.set_text('')
        else:
            self.unreviewed_changes.set_text('%i ' % unreviewed_changes)
        if open_changes is None:
            self.open_changes.set_text('')
        else:
            self.open_changes.set_text('%i ' % open_changes)

    def toggleMark(self):
        self.mark = not self.mark
        if self.mark:
            style = 'marked-project'
        else:
            style = self._style
        self.row_style.set_attr_map({None: style})
        self._setName(self.topic_name)

class ProjectListHeader(urwid.WidgetWrap):
    def __init__(self):
        cols = [urwid.Text(u' Project'),
                (11, urwid.Text(u'Unreviewed')),
                (5, urwid.Text(u'Open'))]
        super(ProjectListHeader, self).__init__(urwid.Columns(cols))

@mouse_scroll_decorator.ScrollByWheel
class ProjectListView(urwid.WidgetWrap, mywid.Searchable):
    def getCommands(self):
        return [
            (keymap.TOGGLE_LIST_SUBSCRIBED,
             "Toggle whether only subscribed projects or all projects are listed"),
            (keymap.TOGGLE_LIST_REVIEWED,
             "Toggle listing of projects with unreviewed changes"),
            (keymap.TOGGLE_SUBSCRIBED,
             "Toggle the subscription flag for the selected project"),
            (keymap.REFRESH,
             "Sync subscribed projects"),
            (keymap.TOGGLE_MARK,
             "Toggle the process mark for the selected project"),
            (keymap.NEW_PROJECT_TOPIC,
             "Create project topic"),
            (keymap.DELETE_PROJECT_TOPIC,
             "Delete selected project topic"),
            (keymap.MOVE_PROJECT_TOPIC,
             "Move selected project to topic"),
            (keymap.COPY_PROJECT_TOPIC,
             "Copy selected project to topic"),
            (keymap.REMOVE_PROJECT_TOPIC,
             "Remove selected project from topic"),
            (keymap.RENAME_PROJECT_TOPIC,
             "Rename selected project topic"),
            (keymap.INTERACTIVE_SEARCH,
             "Interactive search"),
        ]

    def help(self):
        key = self.app.config.keymap.formatKeys
        commands = self.getCommands()
        return [(c[0], key(c[0]), c[1]) for c in commands]

    def __init__(self, app):
        super(ProjectListView, self).__init__(urwid.Pile([]))
        self.log = logging.getLogger('gertty.view.project_list')
        self.searchInit()
        self.app = app
        self.unreviewed = True
        self.subscribed = True
        self.project_rows = {}
        self.topic_rows = {}
        self.open_topics = set()
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

    def advance(self):
        pos = self.listbox.focus_position
        if pos < len(self.listbox.body)-1:
            pos += 1
            self.listbox.focus_position = pos

    def _deleteRow(self, row):
        if row in self.listbox.body:
            self.listbox.body.remove(row)
        if isinstance(row, ProjectRow):
            del self.project_rows[(row.topic_key, row.project_key)]
        else:
            del self.topic_rows[row.topic_key]

    def _projectRow(self, i, project, topic):
        # Ensure that the row at i is the given project.  If the row
        # already exists somewhere in the list, delete all rows
        # between i and the row and then update the row.  If the row
        # does not exist, insert the row at position i.
        topic_key = topic and topic.key or None
        key = (topic_key, project.key)
        row = self.project_rows.get(key)
        while row:  # This is "if row: while True:".
            if i >= len(self.listbox.body):
                break
            current_row = self.listbox.body[i]
            if (isinstance(current_row, ProjectRow) and
                current_row.project_key == project.key):
                break
            self._deleteRow(current_row)
        if not row:
            row = ProjectRow(self.app, project, topic, self.onSelect)
            self.listbox.body.insert(i, row)
            self.project_rows[key] = row
        else:
            row.update(project)
        return i+1

    def _topicRow(self, i, topic):
        row = self.topic_rows.get(topic.key)
        while row:  # This is "if row: while True:".
            if i >= len(self.listbox.body):
                break
            current_row = self.listbox.body[i]
            if (isinstance(current_row, TopicRow) and
                current_row.topic_key == topic.key):
                break
            self._deleteRow(current_row)
        if not row:
            row = TopicRow(topic, self.onSelectTopic)
            self.listbox.body.insert(i, row)
            self.topic_rows[topic.key] = row
        else:
            row.update(topic)
        return i + 1

    def refresh(self):
        if self.subscribed:
            self.title = u'Subscribed projects'
            self.short_title = self.title[:]
            if self.unreviewed:
                self.title += u' with unreviewed changes'
        else:
            self.title = u'All projects'
            self.short_title = self.title[:]
        self.app.status.update(title=self.title)
        with self.app.db.getSession() as session:
            i = 0
            for project in session.getProjects(topicless=True,
                    subscribed=self.subscribed, unreviewed=self.unreviewed):
                #self.log.debug("project: %s" % project.name)
                i = self._projectRow(i, project, None)
            for topic in session.getTopics():
                #self.log.debug("topic: %s" % topic.name)
                i = self._topicRow(i, topic)
                topic_unreviewed = 0
                topic_open = 0
                for project in topic.projects:
                    #self.log.debug("  project: %s" % project.name)
                    cache = self.app.project_cache.get(project)
                    topic_unreviewed += cache['unreviewed_changes']
                    topic_open += cache['open_changes']
                    if self.subscribed:
                        if not project.subscribed:
                            continue
                        if self.unreviewed and not cache['unreviewed_changes']:
                            continue
                    if topic.key in self.open_topics:
                        i = self._projectRow(i, project, topic)
                topic_row = self.topic_rows.get(topic.key)
                topic_row.update(topic, topic_unreviewed, topic_open)
        while i < len(self.listbox.body):
            current_row = self.listbox.body[i]
            self._deleteRow(current_row)

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

    def onSelectTopic(self, button, data):
        topic_key = data[0]
        self.open_topics ^= set([topic_key])
        self.refresh()

    def toggleMark(self):
        if not len(self.listbox.body):
            return
        pos = self.listbox.focus_position
        row = self.listbox.body[pos]
        row.toggleMark()
        self.advance()

    def createTopic(self):
        dialog = mywid.LineEditDialog(self.app, 'Topic', 'Create a new topic.',
                                      'Topic: ', '', self.app.ring)
        urwid.connect_signal(dialog, 'save',
            lambda button: self.closeCreateTopic(dialog, True))
        urwid.connect_signal(dialog, 'cancel',
            lambda button: self.closeCreateTopic(dialog, False))
        self.app.popup(dialog)

    def closeCreateTopic(self, dialog, save):
        if save:
            last_topic_key = None
            for row in self.listbox.body:
                if isinstance(row, TopicRow):
                    last_topic_key = row.topic_key
            with self.app.db.getSession() as session:
                if last_topic_key:
                    last_topic = session.getTopic(last_topic_key)
                    seq = last_topic.sequence + 1
                else:
                    seq = 0
                t = session.createTopic(dialog.entry.edit_text, seq)
        self.app.backScreen()

    def deleteTopic(self):
        rows = self.getSelectedRows(TopicRow)
        if not rows:
            return
        with self.app.db.getSession() as session:
            for row in rows:
                topic = session.getTopic(row.topic_key)
                session.delete(topic)
        self.refresh()

    def renameTopic(self):
        pos = self.listbox.focus_position
        row = self.listbox.body[pos]
        if not isinstance(row, TopicRow):
            return
        with self.app.db.getSession() as session:
            topic = session.getTopic(row.topic_key)
            name = topic.name
            key = topic.key
        dialog = mywid.LineEditDialog(self.app, 'Topic', 'Rename a new topic.',
                                      'Topic: ', name, self.app.ring)
        urwid.connect_signal(dialog, 'save',
            lambda button: self.closeRenameTopic(dialog, True, key))
        urwid.connect_signal(dialog, 'cancel',
            lambda button: self.closeRenameTopic(dialog, False, key))
        self.app.popup(dialog)

    def closeRenameTopic(self, dialog, save, key):
        if save:
            with self.app.db.getSession() as session:
                topic = session.getTopic(key)
                topic.name = dialog.entry.edit_text
        self.app.backScreen()

    def getSelectedRows(self, cls):
        ret = []
        for row in self.listbox.body:
            if isinstance(row, cls) and row.mark:
                ret.append(row)
        if ret:
            return ret
        pos = self.listbox.focus_position
        row = self.listbox.body[pos]
        if isinstance(row, cls):
            return [row]
        return []

    def copyMoveToTopic(self, move):
        if move:
            verb = 'Move'
        else:
            verb = 'Copy'
        rows = self.getSelectedRows(ProjectRow)
        if not rows:
            return

        with self.app.db.getSession() as session:
            topics = [(t.key, t.name) for t in session.getTopics()]

        dialog = TopicSelectDialog('%s to Topic' % verb, topics)
        urwid.connect_signal(dialog, 'ok',
            lambda button: self.closeCopyMoveToTopic(dialog, True, rows, move))
        urwid.connect_signal(dialog, 'cancel',
            lambda button: self.closeCopyMoveToTopic(dialog, False, rows, move))
        self.app.popup(dialog)

    def closeCopyMoveToTopic(self, dialog, save, rows, move):
        error = None
        if save:
            with self.app.db.getSession() as session:
                key = dialog.getSelected()
                new_topic = session.getTopic(key)
                if not new_topic:
                    error = "Unable to find topic %s" % topic_name
                else:
                    for row in rows:
                        project = session.getProject(row.project_key)
                        if move and row.topic_key:
                            old_topic = session.getTopic(row.topic_key)
                            self.log.debug("Remove %s from %s" % (project, old_topic))
                            old_topic.removeProject(project)
                        self.log.debug("Add %s to %s" % (project, new_topic))
                        new_topic.addProject(project)
        self.app.backScreen()
        if error:
            self.app.error(error)

    def moveToTopic(self):
        self.copyMoveToTopic(True)

    def copyToTopic(self):
        self.copyMoveToTopic(False)

    def removeFromTopic(self):
        rows = self.getSelectedRows(ProjectRow)
        rows = [r for r in rows if r.topic_key]
        if not rows:
            return
        with self.app.db.getSession() as session:
            for row in rows:
                project = session.getProject(row.project_key)
                topic = session.getTopic(row.topic_key)
                self.log.debug("Remove %s from %s" % (project, topic))
                topic.removeProject(project)
        self.refresh()

    def toggleSubscribed(self):
        rows = self.getSelectedRows(ProjectRow)
        if not rows:
            return
        keys = [row.project_key for row in rows]
        subscribed_keys = []
        with self.app.db.getSession() as session:
            for key in keys:
                project = session.getProject(key)
                project.subscribed = not project.subscribed
                if project.subscribed:
                    subscribed_keys.append(key)
        for row in rows:
            if row.mark:
                row.toggleMark()
        for key in subscribed_keys:
            self.app.sync.submitTask(sync.SyncProjectTask(key))
        self.refresh()

    def keypress(self, size, key):
        if self.searchKeypress(size, key):
            return None

        if not self.app.input_buffer:
            key = super(ProjectListView, self).keypress(size, key)
        keys = self.app.input_buffer + [key]
        commands = self.app.config.keymap.getCommands(keys)
        ret = self.handleCommands(commands)
        if ret is True:
            if keymap.FURTHER_INPUT not in commands:
                self.app.clearInputBuffer()
            return None
        return key

    def handleCommands(self, commands):
        if keymap.TOGGLE_LIST_REVIEWED in commands:
            self.unreviewed = not self.unreviewed
            self.refresh()
            return True
        if keymap.TOGGLE_LIST_SUBSCRIBED in commands:
            self.subscribed = not self.subscribed
            self.refresh()
            return True
        if keymap.TOGGLE_SUBSCRIBED in commands:
            self.toggleSubscribed()
            return True
        if keymap.TOGGLE_MARK in commands:
            self.toggleMark()
            return True
        if keymap.NEW_PROJECT_TOPIC in commands:
            self.createTopic()
            return True
        if keymap.DELETE_PROJECT_TOPIC in commands:
            self.deleteTopic()
            return True
        if keymap.COPY_PROJECT_TOPIC in commands:
            self.copyToTopic()
            return True
        if keymap.MOVE_PROJECT_TOPIC in commands:
            self.moveToTopic()
            return True
        if keymap.REMOVE_PROJECT_TOPIC in commands:
            self.removeFromTopic()
            return True
        if keymap.RENAME_PROJECT_TOPIC in commands:
            self.renameTopic()
            return True
        if keymap.REFRESH in commands:
            self.app.sync.submitTask(
                sync.SyncSubscribedProjectsTask(sync.HIGH_PRIORITY))
            self.app.status.update()
            self.refresh()
            return True
        if keymap.INTERACTIVE_SEARCH in commands:
            self.searchStart()
            return True
        return False
