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

from gertty import keymap
from gertty import mywid
from gertty import sync
from gertty.view import change as view_change
from gertty.view import mouse_scroll_decorator
import gertty.view


class ThreadStack(object):
    def __init__(self):
        self.stack = []

    def push(self, change, children):
        self.stack.append([change, children])

    def pop(self):
        change = None
        while self.stack:
            if self.stack[-1][1]:
                # handle children at the tip
                return self.stack[-1][1].pop(0)
            else:
                # current tip has no children, walk up
                self.stack.pop()
                continue
        return None

    def countChildren(self):
        return [len(x[1]) for x in self.stack]

class ChangeRow(urwid.Button):
    change_focus_map = {None: 'focused',
                        'unreviewed-change': 'focused-unreviewed-change',
                        'reviewed-change': 'focused-reviewed-change',
                        'starred-change': 'focused-starred-change',
                        'positive-label': 'focused-positive-label',
                        'negative-label': 'focused-negative-label',
                        'min-label': 'focused-min-label',
                        'max-label': 'focused-max-label',
                        }

    def selectable(self):
        return True

    def __init__(self, app, change, categories, project=False, owner=False,
                 updated=False, callback=None):
        super(ChangeRow, self).__init__('', on_press=callback, user_data=change.key)
        self.app = app
        self.change_key = change.key
        self.subject = urwid.Text(u'', wrap='clip')
        self.number = urwid.Text(u'')
        self.updated = urwid.Text(u'')
        self.project = urwid.Text(u'', wrap='clip')
        self.owner = urwid.Text(u'', wrap='clip')
        cols = [(6, self.number), ('weight', 4, self.subject)]
        if project:
            cols.append(('weight', 1, self.project))
        if owner:
            cols.append(('weight', 2, self.owner))
        if updated:
            cols.append(('fixed', 10, self.updated))
        self.num_columns = len(cols)
        self.columns = urwid.Columns(cols, dividechars=1)
        self.row_style = urwid.AttrMap(self.columns, '')
        self._w = urwid.AttrMap(self.row_style, None, focus_map=self.change_focus_map)
        self.update(change, categories)

    def update(self, change, categories):
        if change.reviewed or change.hidden:
            style = 'reviewed-change'
        else:
            style = 'unreviewed-change'
        if hasattr(change, '_subject'):
            subject = change._subject
        else:
            subject = change.subject
        flag = ' '
        color = None
        if change.starred:
            flag = '*'
            style = 'starred-change'
        subject = flag + subject
        self.row_style.set_attr_map({None: style})
        self.subject.set_text(subject)
        self.number.set_text(str(change.number))
        self.project.set_text(change.project.name.split('/')[-1])
        self.owner.set_text(change.owner_name)
        today = self.app.time(datetime.datetime.utcnow()).date()
        updated_time = self.app.time(change.updated)
        if today == updated_time.date():
            self.updated.set_text(updated_time.strftime("%I:%M %p").upper())
        else:
            self.updated.set_text(updated_time.strftime("%Y-%m-%d"))
        del self.columns.contents[self.num_columns:]
        for category in categories:
            v = change.getMaxForCategory(category)
            cat_min, cat_max = change.getMinMaxPermittedForCategory(category)
            if v == 0:
                val = ''
            elif v > 0:
                val = '%2i' % v
                if v == cat_max:
                    val = ('max-label', val)
                else:
                    val = ('positive-label', val)
            else:
                val = '%i' % v
                if v == cat_min:
                    val = ('min-label', val)
                else:
                    val = ('negative-label', val)
            self.columns.contents.append((urwid.Text(val), self.columns.options('given', 2)))

class ChangeListHeader(urwid.WidgetWrap):
    def __init__(self, project=False, owner=False, updated=False):
        cols = [(6, urwid.Text(u'Number')), ('weight', 4, urwid.Text(u' Subject'))]
        if project:
            cols.append(('weight', 1, urwid.Text(u'Project')))
        if owner:
            cols.append(('weight', 2, urwid.Text(u'Owner')))
        if updated:
            cols.append(('fixed', 10, urwid.Text(u'Updated')))
        self.num_columns = len(cols)
        super(ChangeListHeader, self).__init__(urwid.Columns(cols, dividechars=1))

    def update(self, categories):
        del self._w.contents[self.num_columns:]
        for category in categories:
            self._w.contents.append((urwid.Text(' %s' % category[0]), self._w.options('given', 2)))

@mouse_scroll_decorator.ScrollByWheel
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
            (key(keymap.TOGGLE_STARRED),
             "Toggle the starred flag for the currently selected change"),
            (key(keymap.REFRESH),
             "Sync all projects"),
            (key(keymap.SORT_BY_NUMBER),
             "Sort changes by number"),
            (key(keymap.SORT_BY_UPDATED),
             "Sort changes by how recently the change was updated"),
            (key(keymap.SORT_BY_REVERSE),
             "Reverse the sort")
            ]

    def __init__(self, app, query, query_desc=None, project_key=None,
                 unreviewed=False):
        super(ChangeListView, self).__init__(urwid.Pile([]))
        self.log = logging.getLogger('gertty.view.change_list')
        self.app = app
        self.query = query
        self.query_desc = query_desc or query
        self.unreviewed = unreviewed
        self.change_rows = {}
        self.listbox = urwid.ListBox(urwid.SimpleFocusListWalker([]))
        self.display_owner = self.display_project = self.display_updated = True
        self.project_key = project_key
        if project_key is not None:
            self.display_project = False
        self.sort_by = app.config.change_list_options['sort-by']
        self.reverse = app.config.change_list_options['reverse']
        self.header = ChangeListHeader(self.display_project, self.display_owner,
                                       self.display_updated)
        self.categories = []
        self.refresh()
        self._w.contents.append((app.header, ('pack', 1)))
        self._w.contents.append((urwid.Divider(), ('pack', 1)))
        self._w.contents.append((urwid.AttrWrap(self.header, 'table-header'), ('pack', 1)))
        self._w.contents.append((self.listbox, ('weight', 1)))
        self._w.set_focus(3)

    def interested(self, event):
        if not ((self.project_key is not None and
                 isinstance(event, sync.ChangeAddedEvent) and
                 self.project_key == event.project_key)
                or
                (self.project_key is None and
                 isinstance(event, sync.ChangeAddedEvent))
                or
                (isinstance(event, sync.ChangeUpdatedEvent) and
                 event.change_key in self.change_rows.keys())):
            self.log.debug("Ignoring refresh change list due to event %s" % (event,))
            return False
        self.log.debug("Refreshing change list due to event %s" % (event,))
        return True

    def refresh(self):
        unseen_keys = set(self.change_rows.keys())
        with self.app.db.getSession() as session:
            change_list = session.getChanges(self.query, self.unreviewed,
                                             sort_by=self.sort_by)
            if self.unreviewed:
                self.title = u'Unreviewed changes in %s' % self.query_desc
            else:
                self.title = u'All changes in %s' % self.query_desc
            self.app.status.update(title=self.title)
            categories = set()
            for change in change_list:
                categories |= set(change.getCategories())
            self.categories = sorted(categories)
            i = 0
            if self.reverse:
                change_list.reverse()
            if self.app.config.thread_changes:
                change_list = self._threadChanges(change_list)
            new_rows = []
            if len(self.listbox.body):
                focus_pos = self.listbox.focus_position
                focus_row = self.listbox.body[focus_pos]
            else:
                focus_pos = 0
                focus_row = None
            for change in change_list:
                row = self.change_rows.get(change.key)
                if not row:
                    row = ChangeRow(self.app, change, self.categories,
                                    self.display_project,
                                    self.display_owner,
                                    self.display_updated,
                                    callback=self.onSelect)
                    self.listbox.body.insert(i, row)
                    self.change_rows[change.key] = row
                else:
                    row.update(change, self.categories)
                    unseen_keys.remove(change.key)
                new_rows.append(row)
                i += 1
            self.listbox.body[:] = new_rows
            if focus_row in self.listbox.body:
                pos = self.listbox.body.index(focus_row)
            else:
                pos = min(focus_pos, len(self.listbox.body)-1)
            self.listbox.body.set_focus(pos)
            if change_list:
                self.header.update(self.categories)
        for key in unseen_keys:
            row = self.change_rows[key]
            del self.change_rows[key]

    def _threadChanges(self, changes):
        ret = []
        stack = ThreadStack()
        children = {}
        commits = {}
        orphans = changes[:]
        for change in changes:
            for revision in change.revisions:
                commits[revision.commit] = change
        for change in changes:
            revision = change.revisions[-1]
            parent = commits.get(revision.parent, None)
            if parent:
                if parent.revisions[-1].commit != revision.parent:
                    # Our parent is an outdated revision.  This could
                    # cause a cycle, so skip.  This change will not
                    # appear in the thread, but will still appear in
                    # the list.  TODO: use color to indicate it
                    # depends on an outdated change.
                    continue
                if change in orphans:
                    orphans.remove(change)
                v = children.get(parent, [])
                v.append(change)
                children[parent] = v
        if orphans:
            change = orphans.pop(0)
        else:
            change = None
        while change:
            prefix = ''
            stack_children = stack.countChildren()
            for i, nchildren in enumerate(stack_children):
                if nchildren:
                    if i+1 == len(stack_children):
                        prefix += u'\u251c'
                    else:
                        prefix += u'\u2502'
                else:
                    if i+1 == len(stack_children):
                        prefix += u'\u2514'
                    else:
                        prefix += u' '
                if i+1 == len(stack_children):
                    prefix += u'\u2500'
                else:
                    prefix += u' '
            subject = '%s%s' % (prefix, change.subject)
            change._subject = subject
            ret.append(change)
            if change in children:
                stack.push(change, children[change])
            change = stack.pop()
            if (not change) and orphans:
                change = orphans.pop(0)
        assert len(ret) == len(changes)
        return ret

    def clearChangeList(self):
        for key, value in self.change_rows.iteritems():
            self.listbox.body.remove(value)
        self.change_rows = {}

    def getNextChangeKey(self, change_key):
        row = self.change_rows.get(change_key)
        try:
            i = self.listbox.body.index(row)
        except ValueError:
            return None
        if i+1 >= len(self.listbox.body):
            return None
        row = self.listbox.body[i+1]
        return row.change_key

    def getPrevChangeKey(self, change_key):
        row = self.change_rows.get(change_key)
        try:
            i = self.listbox.body.index(row)
        except ValueError:
            return None
        if i <= 0:
            return None
        row = self.listbox.body[i-1]
        return row.change_key

    def toggleReviewed(self, change_key):
        with self.app.db.getSession() as session:
            change = session.getChange(change_key)
            change.reviewed = not change.reviewed
            ret = change.reviewed
            reviewed_str = 'reviewed' if change.reviewed else 'unreviewed'
            self.log.debug("Set change %s to %s", change_key, reviewed_str)
        return ret

    def toggleStarred(self, change_key):
        with self.app.db.getSession() as session:
            change = session.getChange(change_key)
            change.starred = not change.starred
            ret = change.starred
            change.pending_starred = True
        self.app.sync.submitTask(
            sync.ChangeStarredTask(change_key, sync.HIGH_PRIORITY))
        return ret

    def toggleHidden(self, change_key):
        with self.app.db.getSession() as session:
            change = session.getChange(change_key)
            change.hidden = not change.hidden
            ret = change.hidden
            hidden_str = 'hidden' if change.hidden else 'visible'
            self.log.debug("Set change %s to %s", change_key, hidden_str)
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
            change_key = self.listbox.body[pos].change_key
            reviewed = self.toggleReviewed(change_key)
            if self.unreviewed and reviewed:
                # Here we can avoid a full refresh by just removing the particular
                # row from the change list if the view is for the unreviewed changes
                # only.
                row = self.change_rows[change_key]
                self.listbox.body.remove(row)
                del self.change_rows[change_key]
            else:
                # Just fall back on doing a full refresh if we're in a situation
                # where we're not just popping a row from the list of unreviewed
                # changes.
                self.refresh()
            return None
        if keymap.TOGGLE_HIDDEN in commands:
            if not len(self.listbox.body):
                return None
            pos = self.listbox.focus_position
            change_key = self.listbox.body[pos].change_key
            hidden = self.toggleHidden(change_key)
            if hidden:
                # Here we can avoid a full refresh by just removing the particular
                # row from the change list
                row = self.change_rows[change_key]
                self.listbox.body.remove(row)
                del self.change_rows[change_key]
            else:
                # Just fall back on doing a full refresh if we're in a situation
                # where we're not just popping a row from the list of changes.
                self.refresh()
            return None
        if keymap.TOGGLE_STARRED in commands:
            if not len(self.listbox.body):
                return None
            pos = self.listbox.focus_position
            change_key = self.listbox.body[pos].change_key
            starred = self.toggleStarred(change_key)
            row = self.change_rows[change_key]
            with self.app.db.getSession() as session:
                change = session.getChange(change_key)
                row.update(change, self.categories)
            return None
        if keymap.REFRESH in commands:
            self.app.sync.submitTask(
                sync.SyncSubscribedProjectsTask(sync.HIGH_PRIORITY))
            self.app.status.update()
            return None
        if keymap.SORT_BY_NUMBER in commands:
            if not len(self.listbox.body):
                return None
            self.sort_by = 'number'
            self.clearChangeList()
            self.refresh()
            return None
        if keymap.SORT_BY_UPDATED in commands:
            if not len(self.listbox.body):
                return None
            self.sort_by = 'updated'
            self.clearChangeList()
            self.refresh()
            return None
        if keymap.SORT_BY_REVERSE in commands:
            if not len(self.listbox.body):
                return None
            if self.reverse:
                self.reverse = False
            else:
                self.reverse = True
            self.clearChangeList()
            self.refresh()
            return None
        return key

    def onSelect(self, button, change_key):
        try:
            view = view_change.ChangeView(self.app, change_key)
            self.app.changeScreen(view)
        except gertty.view.DisplayError as e:
            self.app.error(e.message)
