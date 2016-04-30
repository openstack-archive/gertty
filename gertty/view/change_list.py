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

import six
import urwid

from gertty import keymap
from gertty import mywid
from gertty import sync
from gertty.view import change as view_change
from gertty.view import mouse_scroll_decorator
import gertty.view


class ColumnInfo(object):
    def __init__(self, name, packing, value):
        self.name = name
        self.packing = packing
        self.value = value
        self.options = (packing, value)
        if packing == 'given':
            self.spacing = value + 1
        else:
            self.spacing = (value * 8) + 1


COLUMNS = [
    ColumnInfo('Number',  'given',   6),
    ColumnInfo('Subject', 'weight',  4),
    ColumnInfo('Project', 'weight',  1),
    ColumnInfo('Branch',  'weight',  1),
    ColumnInfo('Topic',   'weight',  1),
    ColumnInfo('Owner',   'weight',  1),
    ColumnInfo('Updated', 'given',  10),
]


class ThreadStack(object):
    def __init__(self):
        self.stack = []

    def push(self, change, children):
        self.stack.append([change, children])

    def pop(self):
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


class ChangeListColumns(object):
    def updateColumns(self):
        del self.columns.contents[:]
        cols = self.columns.contents
        options = self.columns.options

        for colinfo in COLUMNS:
            if colinfo.name in self.enabled_columns:
                attr = colinfo.name.lower().replace(' ', '_')
                cols.append((getattr(self, attr),
                             options(*colinfo.options)))

        for c in self.category_columns:
            cols.append(c)


class ChangeRow(urwid.Button, ChangeListColumns):
    change_focus_map = {None: 'focused',
                        'unreviewed-change': 'focused-unreviewed-change',
                        'reviewed-change': 'focused-reviewed-change',
                        'starred-change': 'focused-starred-change',
                        'held-change': 'focused-held-change',
                        'marked-change': 'focused-marked-change',
                        'positive-label': 'focused-positive-label',
                        'negative-label': 'focused-negative-label',
                        'min-label': 'focused-min-label',
                        'max-label': 'focused-max-label',
                        }

    def selectable(self):
        return True

    def __init__(self, app, change, prefix, categories,
                 enabled_columns, callback=None):
        super(ChangeRow, self).__init__('', on_press=callback, user_data=change.key)
        self.app = app
        self.change_key = change.key
        self.prefix = prefix
        self.enabled_columns = enabled_columns
        self.subject = mywid.SearchableText(u'', wrap='clip')
        self.number = mywid.SearchableText(u'')
        self.updated = mywid.SearchableText(u'')
        self.project = mywid.SearchableText(u'', wrap='clip')
        self.owner = mywid.SearchableText(u'', wrap='clip')
        self.branch = mywid.SearchableText(u'', wrap='clip')
        self.topic = mywid.SearchableText(u'', wrap='clip')
        self.mark = False
        self.columns = urwid.Columns([], dividechars=1)
        self.row_style = urwid.AttrMap(self.columns, '')
        self._w = urwid.AttrMap(self.row_style, None, focus_map=self.change_focus_map)
        self.category_columns = []
        self.update(change, categories)

    def search(self, search, attribute):
        if self.subject.search(search, attribute):
            return True
        if self.number.search(search, attribute):
            return True
        if self.project.search(search, attribute):
            return True
        if self.branch.search(search, attribute):
            return True
        if self.owner.search(search, attribute):
            return True
        if self.topic.search(search, attribute):
            return True
        if self.updated.search(search, attribute):
            return True
        return False

    def update(self, change, categories):
        if change.reviewed or change.hidden:
            style = 'reviewed-change'
        else:
            style = 'unreviewed-change'
        subject = '%s%s' % (self.prefix, change.subject)
        flag = ' '
        if change.starred:
            flag = '*'
            style = 'starred-change'
        if change.held:
            flag = '!'
            style = 'held-change'
        if self.mark:
            flag = '%'
            style = 'marked-change'
        subject = flag + subject
        self.row_style.set_attr_map({None: style})
        self.subject.set_text(subject)
        self.number.set_text(str(change.number))
        self.project.set_text(change.project.name.split('/')[-1])
        self.owner.set_text(change.owner_name)
        self.branch.set_text(change.branch or '')
        self.topic.set_text(change.topic or '')
        self.project_name = change.project.name
        self.commit_sha = change.revisions[-1].commit
        self.current_revision_key = change.revisions[-1].key
        today = self.app.time(datetime.datetime.utcnow()).date()
        updated_time = self.app.time(change.updated)
        if today == updated_time.date():
            self.updated.set_text(updated_time.strftime("%I:%M %p").upper())
        else:
            self.updated.set_text(updated_time.strftime("%Y-%m-%d"))

        self.category_columns = []
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
            self.category_columns.append((urwid.Text(val),
                                          self.columns.options('given', 2)))
        self.updateColumns()

class ChangeListHeader(urwid.WidgetWrap, ChangeListColumns):
    def __init__(self, enabled_columns):
        self.enabled_columns = enabled_columns
        self.subject = urwid.Text(u'Subject', wrap='clip')
        self.number = urwid.Text(u'Number')
        self.updated = urwid.Text(u'Updated')
        self.project = urwid.Text(u'Project', wrap='clip')
        self.owner = urwid.Text(u'Owner', wrap='clip')
        self.branch = urwid.Text(u'Branch', wrap='clip')
        self.topic = urwid.Text(u'Topic', wrap='clip')
        self.columns = urwid.Columns([], dividechars=1)
        self.category_columns = []
        super(ChangeListHeader, self).__init__(self.columns)

    def update(self, categories):
        self.category_columns = []
        for category in categories:
            self.category_columns.append((urwid.Text(' %s' % category[0]),
                                          self._w.options('given', 2)))
        self.updateColumns()


@mouse_scroll_decorator.ScrollByWheel
class ChangeListView(urwid.WidgetWrap, mywid.Searchable):
    required_columns = set(['Number', 'Subject', 'Updated'])
    optional_columns = set(['Topic', 'Branch'])

    def getCommands(self):
        if self.project_key:
            refresh_help = "Sync current project"
        else:
            refresh_help = "Sync subscribed projects"
        return [
            (keymap.TOGGLE_HELD,
             "Toggle the held flag for the currently selected change"),
            (keymap.LOCAL_CHECKOUT,
             "Checkout the most recent revision of the selected change into the local repo"),
            (keymap.TOGGLE_HIDDEN,
             "Toggle the hidden flag for the currently selected change"),
            (keymap.TOGGLE_LIST_REVIEWED,
             "Toggle whether only unreviewed or all changes are displayed"),
            (keymap.TOGGLE_REVIEWED,
             "Toggle the reviewed flag for the currently selected change"),
            (keymap.TOGGLE_STARRED,
             "Toggle the starred flag for the currently selected change"),
            (keymap.TOGGLE_MARK,
             "Toggle the process mark for the currently selected change"),
            (keymap.REFINE_CHANGE_SEARCH,
             "Refine the current search query"),
            (keymap.ABANDON_CHANGE,
             "Abandon the marked changes"),
            (keymap.EDIT_TOPIC,
             "Set the topic of the marked changes"),
            (keymap.RESTORE_CHANGE,
             "Restore the marked changes"),
            (keymap.REFRESH,
             refresh_help),
            (keymap.REVIEW,
             "Leave reviews for the marked changes"),
            (keymap.SORT_BY_NUMBER,
             "Sort changes by number"),
            (keymap.SORT_BY_UPDATED,
             "Sort changes by how recently the change was updated"),
            (keymap.SORT_BY_REVERSE,
             "Reverse the sort"),
            (keymap.LOCAL_CHERRY_PICK,
             "Cherry-pick the most recent revision of the selected change onto the local repo"),
            (keymap.INTERACTIVE_SEARCH,
             "Interactive search"),
            ]

    def help(self):
        key = self.app.config.keymap.formatKeys
        commands = self.getCommands()
        return [(c[0], key(c[0]), c[1]) for c in commands]

    def __init__(self, app, query, query_desc=None, project_key=None,
                 unreviewed=False, sort_by=None, reverse=None):
        super(ChangeListView, self).__init__(urwid.Pile([]))
        self.log = logging.getLogger('gertty.view.change_list')
        self.searchInit()
        self.app = app
        self.query = query
        self.query_desc = query_desc or query
        self.unreviewed = unreviewed
        self.change_rows = {}
        self.enabled_columns = set()
        for colinfo in COLUMNS:
            if (colinfo.name in self.required_columns or
                colinfo.name not in self.optional_columns):
                self.enabled_columns.add(colinfo.name)
        self.disabled_columns = set()
        self.listbox = urwid.ListBox(urwid.SimpleFocusListWalker([]))
        self.project_key = project_key
        if 'Project' not in self.required_columns and project_key is not None:
            self.enabled_columns.discard('Project')
            self.disabled_columns.add('Project')
        if 'Owner' not in self.required_columns and 'owner:' in query:
            # This could be or'd with something else, but probably
            # not.
            self.enabled_columns.discard('Owner')
            self.disabled_columns.add('Owner')
        self.sort_by = sort_by or app.config.change_list_options['sort-by']
        if reverse is not None:
            self.reverse = reverse
        else:
            self.reverse = app.config.change_list_options['reverse']
        self.header = ChangeListHeader(self.enabled_columns)
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
            self.short_title = self.query_desc
            if '/' in self.short_title and ' ' not in self.short_title:
                i = self.short_title.rfind('/')
                self.short_title = self.short_title[i+1:]
            self.app.status.update(title=self.title)
            categories = set()
            for change in change_list:
                categories |= set(change.getCategories())
            self.categories = sorted(categories)
            self.chooseColumns()
            self.header.update(self.categories)
            i = 0
            if self.reverse:
                change_list.reverse()
            if self.app.config.thread_changes:
                change_list, prefixes = self._threadChanges(change_list)
            else:
                prefixes = {}
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
                    row = ChangeRow(self.app, change,
                                    prefixes.get(change.key),
                                    self.categories,
                                    self.enabled_columns,
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
        for key in unseen_keys:
            row = self.change_rows[key]
            del self.change_rows[key]

    def chooseColumns(self):
        currently_enabled_columns = self.enabled_columns.copy()
        size = self.app.loop.screen.get_cols_rows()
        cols = size[0]
        for colinfo in COLUMNS:
            if (colinfo.name not in self.disabled_columns):
                cols -= colinfo.spacing
        cols -= 3 * len(self.categories)

        for colinfo in COLUMNS:
            if colinfo.name in self.optional_columns:
                if cols >= colinfo.spacing:
                    self.enabled_columns.add(colinfo.name)
                    cols -= colinfo.spacing
                else:
                    self.enabled_columns.discard(colinfo.name)
        if currently_enabled_columns != self.enabled_columns:
            self.header.updateColumns()
            for key, value in six.iteritems(self.change_rows):
                value.updateColumns()

    def getQueryString(self):
        if self.project_key is not None:
            return "project:%s %s" % (self.query_desc, self.app.config.project_change_list_query)
        return self.query

    def _threadChanges(self, changes):
        ret = []
        prefixes = {}
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
            prefixes[change.key] = prefix
            ret.append(change)
            if change in children:
                stack.push(change, children[change])
            change = stack.pop()
            if (not change) and orphans:
                change = orphans.pop(0)
        assert len(ret) == len(changes)
        return (ret, prefixes)

    def clearChangeList(self):
        for key, value in six.iteritems(self.change_rows):
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
            self.app.project_cache.clear(change.project)
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

    def toggleHeld(self, change_key):
        return self.app.toggleHeldChange(change_key)

    def toggleHidden(self, change_key):
        with self.app.db.getSession() as session:
            change = session.getChange(change_key)
            change.hidden = not change.hidden
            ret = change.hidden
            hidden_str = 'hidden' if change.hidden else 'visible'
            self.log.debug("Set change %s to %s", change_key, hidden_str)
        return ret

    def advance(self):
        pos = self.listbox.focus_position
        if pos < len(self.listbox.body)-1:
            pos += 1
            self.listbox.focus_position = pos

    def keypress(self, size, key):
        if self.searchKeypress(size, key):
            return None

        if not self.app.input_buffer:
            key = super(ChangeListView, self).keypress(size, key)
        keys = self.app.input_buffer + [key]
        commands = self.app.config.keymap.getCommands(keys)
        ret = self.handleCommands(commands)
        if ret is True:
            if keymap.FURTHER_INPUT not in commands:
                self.app.clearInputBuffer()
            return None
        return key

    def onResize(self):
        self.chooseColumns()

    def handleCommands(self, commands):
        if keymap.TOGGLE_LIST_REVIEWED in commands:
            self.unreviewed = not self.unreviewed
            self.refresh()
            return True
        if keymap.TOGGLE_REVIEWED in commands:
            if not len(self.listbox.body):
                return True
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
                self.advance()
            return True
        if keymap.TOGGLE_HIDDEN in commands:
            if not len(self.listbox.body):
                return True
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
                self.advance()
            return True
        if keymap.TOGGLE_HELD in commands:
            if not len(self.listbox.body):
                return True
            pos = self.listbox.focus_position
            change_key = self.listbox.body[pos].change_key
            self.toggleHeld(change_key)
            row = self.change_rows[change_key]
            with self.app.db.getSession() as session:
                change = session.getChange(change_key)
                row.update(change, self.categories)
            self.advance()
            return True
        if keymap.TOGGLE_STARRED in commands:
            if not len(self.listbox.body):
                return True
            pos = self.listbox.focus_position
            change_key = self.listbox.body[pos].change_key
            self.toggleStarred(change_key)
            row = self.change_rows[change_key]
            with self.app.db.getSession() as session:
                change = session.getChange(change_key)
                row.update(change, self.categories)
            self.advance()
            return True
        if keymap.TOGGLE_MARK in commands:
            if not len(self.listbox.body):
                return True
            pos = self.listbox.focus_position
            change_key = self.listbox.body[pos].change_key
            row = self.change_rows[change_key]
            row.mark = not row.mark
            with self.app.db.getSession() as session:
                change = session.getChange(change_key)
                row.update(change, self.categories)
            self.advance()
            return True
        if keymap.EDIT_TOPIC in commands:
            self.editTopic()
            return True
        if keymap.REFRESH in commands:
            if self.project_key:
                self.app.sync.submitTask(
                    sync.SyncProjectTask(self.project_key, sync.HIGH_PRIORITY))
            else:
                self.app.sync.submitTask(
                    sync.SyncSubscribedProjectsTask(sync.HIGH_PRIORITY))
            self.app.status.update()
            return True
        if keymap.REVIEW in commands:
            rows = [row for row in self.change_rows.values() if row.mark]
            if not rows:
                pos = self.listbox.focus_position
                rows = [self.listbox.body[pos]]
            self.openReview(rows)
            return True
        if keymap.SORT_BY_NUMBER in commands:
            if not len(self.listbox.body):
                return True
            self.sort_by = 'number'
            self.clearChangeList()
            self.refresh()
            return True
        if keymap.SORT_BY_UPDATED in commands:
            if not len(self.listbox.body):
                return True
            self.sort_by = 'updated'
            self.clearChangeList()
            self.refresh()
            return True
        if keymap.SORT_BY_REVERSE in commands:
            if not len(self.listbox.body):
                return True
            if self.reverse:
                self.reverse = False
            else:
                self.reverse = True
            self.clearChangeList()
            self.refresh()
            return True
        if keymap.LOCAL_CHECKOUT in commands:
            if not len(self.listbox.body):
                return True
            pos = self.listbox.focus_position
            row = self.listbox.body[pos]
            self.app.localCheckoutCommit(row.project_name, row.commit_sha)
            return True
        if keymap.LOCAL_CHERRY_PICK in commands:
            if not len(self.listbox.body):
                return True
            pos = self.listbox.focus_position
            row = self.listbox.body[pos]
            self.app.localCherryPickCommit(row.project_name, row.commit_sha)
            return True
        if keymap.REFINE_CHANGE_SEARCH in commands:
            default = self.getQueryString()
            self.app.searchDialog(default)
            return True
        if keymap.ABANDON_CHANGE in commands:
            self.abandonChange()
            return True
        if keymap.RESTORE_CHANGE in commands:
            self.restoreChange()
            return True
        if keymap.INTERACTIVE_SEARCH in commands:
            self.searchStart()
            return True
        return False

    def onSelect(self, button, change_key):
        try:
            view = view_change.ChangeView(self.app, change_key)
            self.app.changeScreen(view)
        except gertty.view.DisplayError as e:
            self.app.error(str(e))

    def openReview(self, rows):
        dialog = view_change.ReviewDialog(self.app, rows[0].current_revision_key)
        urwid.connect_signal(dialog, 'save',
            lambda button: self.closeReview(dialog, rows, True, False))
        urwid.connect_signal(dialog, 'submit',
            lambda button: self.closeReview(dialog, rows, True, True))
        urwid.connect_signal(dialog, 'cancel',
            lambda button: self.closeReview(dialog, rows, False, False))
        self.app.popup(dialog,
                       relative_width=50, relative_height=75,
                       min_width=60, min_height=20)

    def closeReview(self, dialog, rows, upload, submit):
        approvals, message = dialog.getValues()
        revision_keys = [row.current_revision_key for row in rows]
        message_keys = self.app.saveReviews(revision_keys, approvals,
                                            message, upload, submit)
        if upload:
            for message_key in message_keys:
                self.app.sync.submitTask(
                    sync.UploadReviewTask(message_key, sync.HIGH_PRIORITY))
        self.refresh()
        self.app.backScreen()

    def editTopic(self):
        dialog = view_change.EditTopicDialog(self.app, '')
        urwid.connect_signal(dialog, 'save',
            lambda button: self.closeEditTopic(dialog, True))
        urwid.connect_signal(dialog, 'cancel',
            lambda button: self.closeEditTopic(dialog, False))
        self.app.popup(dialog)

    def closeEditTopic(self, dialog, save):
        if save:
            rows = [row for row in self.change_rows.values() if row.mark]
            if not rows:
                pos = self.listbox.focus_position
                rows = [self.listbox.body[pos]]
            change_keys = [row.change_key for row in rows]
            with self.app.db.getSession() as session:
                for change_key in change_keys:
                    change = session.getChange(change_key)
                    change.topic = dialog.entry.edit_text
                    change.pending_topic = True
                    self.app.sync.submitTask(
                        sync.SetTopicTask(change_key, sync.HIGH_PRIORITY))
        self.app.backScreen()
        self.refresh()

    def abandonChange(self):
        dialog = mywid.TextEditDialog(u'Abandon Change', u'Abandon message:',
                                      u'Abandon Change', u'')
        urwid.connect_signal(dialog, 'cancel', self.app.backScreen)
        urwid.connect_signal(dialog, 'save', lambda button:
                                 self.doAbandonRestoreChange(dialog, 'ABANDONED'))
        self.app.popup(dialog)

    def restoreChange(self):
        dialog = mywid.TextEditDialog(u'Restore Change', u'Restore message:',
                                      u'Restore Change', u'')
        urwid.connect_signal(dialog, 'cancel', self.app.backScreen)
        urwid.connect_signal(dialog, 'save', lambda button:
                             self.doAbandonRestoreChange(dialog, 'NEW'))
        self.app.popup(dialog)

    def doAbandonRestoreChange(self, dialog, state):
        rows = [row for row in self.change_rows.values() if row.mark]
        if not rows:
            pos = self.listbox.focus_position
            rows = [self.listbox.body[pos]]
        change_keys = [row.change_key for row in rows]
        with self.app.db.getSession() as session:
            for change_key in change_keys:
                change = session.getChange(change_key)
                change.status = state
                change.pending_status = True
                change.pending_status_message = dialog.entry.edit_text
                self.app.sync.submitTask(
                    sync.ChangeStatusTask(change_key, sync.HIGH_PRIORITY))
        self.app.backScreen()
        self.refresh()
