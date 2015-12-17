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

import argparse
import datetime
import dateutil
import logging
import os
import Queue
import re
import subprocess
import sys
import textwrap
import threading
import urlparse
import warnings
import webbrowser

import sqlalchemy.exc
import urwid

from gertty import db
from gertty import config
from gertty import gitrepo
from gertty import keymap
from gertty import mywid
from gertty import palette
from gertty import sync
from gertty import search
from gertty import requestsexceptions
from gertty.view import change_list as view_change_list
from gertty.view import project_list as view_project_list
from gertty.view import change as view_change
import gertty.view
import gertty.version

WELCOME_TEXT = """\
Welcome to Gertty!

To get started, you should subscribe to some projects.  Press the "L"
key (shift-L) to list all the projects, navigate to the ones you are
interested in, and then press "s" to subscribe to them.  Gertty will
automatically sync changes in your subscribed projects.

Press the F1 key anywhere to get help.  Your terminal emulator may
require you to press function-F1 or alt-F1 instead.

"""

class StatusHeader(urwid.WidgetWrap):
    def __init__(self, app):
        super(StatusHeader, self).__init__(urwid.Columns([]))
        self.app = app
        self.title_widget = urwid.Text(u'Start')
        self.error_widget = urwid.Text('')
        self.offline_widget = urwid.Text('')
        self.sync_widget = urwid.Text(u'Sync: 0')
        self.held_widget = urwid.Text(u'')
        self._w.contents.append((self.title_widget, ('pack', None, False)))
        self._w.contents.append((urwid.Text(u''), ('weight', 1, False)))
        self._w.contents.append((self.held_widget, ('pack', None, False)))
        self._w.contents.append((self.error_widget, ('pack', None, False)))
        self._w.contents.append((self.offline_widget, ('pack', None, False)))
        self._w.contents.append((self.sync_widget, ('pack', None, False)))
        self.error = None
        self.offline = None
        self.title = None
        self.message = None
        self.sync = None
        self.held = None
        self._error = False
        self._offline = False
        self._title = ''
        self._message = ''
        self._sync = 0
        self._held = 0
        self.held_key = self.app.config.keymap.formatKeys(keymap.LIST_HELD)

    def update(self, title=None, message=None, error=None,
               offline=None, refresh=True, held=None):
        if title is not None:
            self.title = title
        if message is not None:
            self.message = message
        if error is not None:
            self.error = error
        if offline is not None:
            self.offline = offline
        if held is not None:
            self.held = held
        self.sync = self.app.sync.queue.qsize()
        if refresh:
            self.refresh()

    def refresh(self):
        if (self._title != self.title or self._message != self.message):
            self._title = self.title
            self._message = self.message
            t = self.message or self.title
            self.title_widget.set_text(t)
        if self._held != self.held:
            self._held = self.held
            if self._held:
                self.held_widget.set_text(('error', u'Held: %s (%s)' % (self._held, self.held_key)))
            else:
                self.held_widget.set_text(u'')
        if self._error != self.error:
            self._error = self.error
            if self._error:
                self.error_widget.set_text(('error', u' Error'))
            else:
                self.error_widget.set_text(u'')
        if self._offline != self.offline:
            self._offline = self.offline
            if self._offline:
                self.offline_widget.set_text(u' Offline')
            else:
                self.offline_widget.set_text(u'')
        if self._sync != self.sync:
            self._sync = self.sync
            self.sync_widget.set_text(u' Sync: %i' % self._sync)


class SearchDialog(mywid.ButtonDialog):
    signals = ['search', 'cancel']
    def __init__(self, app, default):
        self.app = app
        search_button = mywid.FixedButton('Search')
        cancel_button = mywid.FixedButton('Cancel')
        urwid.connect_signal(search_button, 'click',
                             lambda button:self._emit('search'))
        urwid.connect_signal(cancel_button, 'click',
                             lambda button:self._emit('cancel'))
        super(SearchDialog, self).__init__("Search",
                                           "Enter a change number or search string.",
                                           entry_prompt="Search: ",
                                           entry_text=default,
                                           buttons=[search_button,
                                                    cancel_button],
                                           ring=app.ring)

    def keypress(self, size, key):
        if not self.app.input_buffer:
            key = super(SearchDialog, self).keypress(size, key)
        keys = self.app.input_buffer + [key]
        commands = self.app.config.keymap.getCommands(keys)
        if keymap.ACTIVATE in commands:
            self._emit('search')
            return None
        return key

# From: cpython/file/2.7/Lib/webbrowser.py with modification to
# redirect stdin/out/err.
class BackgroundBrowser(webbrowser.GenericBrowser):
    """Class for all browsers which are to be started in the
       background."""

    def open(self, url, new=0, autoraise=True):
        cmdline = [self.name] + [arg.replace("%s", url)
                                 for arg in self.args]
        inout = file(os.devnull, "r+")
        try:
            if sys.platform[:3] == 'win':
                p = subprocess.Popen(cmdline)
            else:
                setsid = getattr(os, 'setsid', None)
                if not setsid:
                    setsid = getattr(os, 'setpgrp', None)
                p = subprocess.Popen(cmdline, close_fds=True,
                                     stdin=inout, stdout=inout,
                                     stderr=inout, preexec_fn=setsid)
            return (p.poll() is None)
        except OSError:
            return False

class App(object):
    simple_change_search = re.compile('^(\d+|I[a-fA-F0-9]{40})$')

    def __init__(self, server=None, palette='default', keymap='default',
                 debug=False, verbose=False, disable_sync=False,
                 fetch_missing_refs=False, path=config.DEFAULT_CONFIG_PATH):
        self.server = server
        self.config = config.Config(server, palette, keymap, path)
        if debug:
            level = logging.DEBUG
        elif verbose:
            level = logging.INFO
        else:
            level = logging.WARNING
        logging.basicConfig(filename=self.config.log_file, filemode='w',
                            format='%(asctime)s %(message)s',
                            level=level)
        # Python2.6 Logger.setLevel doesn't convert string name
        # to integer code. Here, we set the requests logger level to
        # be less verbose, since our logging output duplicates some
        # requests logging content in places.
        req_level_name = 'WARN'
        req_logger = logging.getLogger('requests')
        if sys.version_info < (2, 7):
            level = logging.getLevelName(req_level_name)
            req_logger.setLevel(level)
        else:
            req_logger.setLevel(req_level_name)
        self.log = logging.getLogger('gertty.App')
        self.log.debug("Starting")

        self.ring = mywid.KillRing()
        self.input_buffer = []
        webbrowser.register('xdg-open', None, BackgroundBrowser("xdg-open"))

        self.fetch_missing_refs = fetch_missing_refs
        self.config.keymap.updateCommandMap()
        self.search = search.SearchCompiler(self.config.username)
        self.db = db.Database(self, self.config.dburi, self.search)
        self.sync = sync.Sync(self)

        self.screens = []
        self.status = StatusHeader(self)
        self.header = urwid.AttrMap(self.status, 'header')
        screen = view_project_list.ProjectListView(self)
        self.status.update(title=screen.title)
        self.updateStatusQueries()
        self.loop = urwid.MainLoop(screen, palette=self.config.palette.getPalette(),
                                   unhandled_input=self.unhandledInput)

        self.sync_pipe = self.loop.watch_pipe(self.refresh)
        self.error_queue = Queue.Queue()
        self.error_pipe = self.loop.watch_pipe(self._errorPipeInput)
        self.logged_warnings = set()

        warnings.showwarning = self._showWarning

        has_subscribed_projects = False
        with self.db.getSession() as session:
            if session.getProjects(subscribed=True):
                has_subscribed_projects = True
        if not has_subscribed_projects:
            self.welcome()

        self.loop.screen.tty_signal_keys(start='undefined', stop='undefined')
        #self.loop.screen.set_terminal_properties(colors=88)
        if not disable_sync:
            self.sync_thread = threading.Thread(target=self.sync.run, args=(self.sync_pipe,))
            self.sync_thread.daemon = True
            self.sync_thread.start()
        else:
            self.sync_thread = None
            self.sync.offline = True
            self.status.update(offline=True)

    def run(self):
        try:
            self.loop.run()
        except KeyboardInterrupt:
            pass

    def _quit(self, widget=None):
        raise urwid.ExitMainLoop()

    def quit(self):
        dialog = mywid.YesNoDialog(u'Quit',
                                   u'Are you sure you want to quit?')
        urwid.connect_signal(dialog, 'no', self.backScreen)
        urwid.connect_signal(dialog, 'yes', self._quit)

        self.popup(dialog)

    def clearInputBuffer(self):
        if self.input_buffer:
            self.input_buffer = []
            self.status.update(message='')

    def changeScreen(self, widget, push=True):
        self.log.debug("Changing screen to %s" % (widget,))
        self.status.update(error=False, title=widget.title)
        if push:
            self.screens.append(self.loop.widget)
        self.clearInputBuffer()
        self.loop.widget = widget

    def backScreen(self, target_widget=None):
        if not self.screens:
            return
        while self.screens:
            widget = self.screens.pop()
            if (not target_widget) or (widget is target_widget):
                break
        self.log.debug("Popping screen to %s" % (widget,))
        if hasattr(widget, 'title'):
            self.status.update(title=widget.title)
        self.clearInputBuffer()
        self.loop.widget = widget
        self.refresh(force=True)

    def findChangeList(self):
        for widget in reversed(self.screens):
            if isinstance(widget, view_change_list.ChangeListView):
                return widget
        return None

    def clearHistory(self):
        self.log.debug("Clearing screen history")
        while self.screens:
            widget = self.screens.pop()
            self.clearInputBuffer()
            self.loop.widget = widget

    def refresh(self, data=None, force=False):
        widget = self.loop.widget
        while isinstance(widget, urwid.Overlay):
            widget = widget.contents[0][0]
        interested = force
        invalidate = False
        try:
            while True:
                event = self.sync.result_queue.get(0)
                if widget.interested(event):
                    interested = True
                if hasattr(event, 'held_changed') and event.held_changed:
                    invalidate = True
        except Queue.Empty:
            pass
        if interested:
            widget.refresh()
        if invalidate:
            self.updateStatusQueries()
        self.status.refresh()

    def updateStatusQueries(self):
        with self.db.getSession() as session:
            held = len(session.getHeld())
            self.status.update(held=held)

    def popup(self, widget,
              relative_width=50, relative_height=25,
              min_width=20, min_height=8):
        self.clearInputBuffer()
        overlay = urwid.Overlay(widget, self.loop.widget,
                                'center', ('relative', relative_width),
                                'middle', ('relative', relative_height),
                                min_width=min_width, min_height=min_height)
        self.log.debug("Overlaying %s on screen %s" % (widget, self.loop.widget))
        self.screens.append(self.loop.widget)
        self.loop.widget = overlay

    def help(self):
        if not hasattr(self.loop.widget, 'help'):
            return
        global_help = [(self.config.keymap.formatKeys(k), t)
                       for (k, t) in mywid.GLOBAL_HELP]
        for d in self.config.dashboards.values():
            global_help.append((keymap.formatKey(d['key']), d['name']))
        parts = [('Global Keys', global_help),
                 ('This Screen', self.loop.widget.help())]
        keylen = 0
        for title, items in parts:
            for keys, text in items:
                keylen = max(len(keys), keylen)
        text = ''
        for title, items in parts:
            if text:
                text += '\n'
            text += title+'\n'
            text += '%s\n' % ('='*len(title),)
            for keys, cmdtext in items:
                text += '{keys:{width}} {text}\n'.format(
                    keys=keys, width=keylen, text=cmdtext)
        dialog = mywid.MessageDialog('Help for %s' % version(), text)
        lines = text.split('\n')
        urwid.connect_signal(dialog, 'close',
            lambda button: self.backScreen())
        self.popup(dialog, min_width=76, min_height=len(lines)+4)

    def welcome(self):
        text = WELCOME_TEXT
        dialog = mywid.MessageDialog('Welcome', text)
        lines = text.split('\n')
        urwid.connect_signal(dialog, 'close',
            lambda button: self.backScreen())
        self.popup(dialog, min_width=76, min_height=len(lines)+4)

    def _syncOneChangeFromQuery(self, query):
        number = changeid = None
        if query.startswith("change:"):
            number = query.split(':')[1].strip()
            try:
                number = int(number)
            except ValueError:
                number = None
                changeid = query.split(':')[1].strip()
        if not (number or changeid):
            return
        with self.db.getSession() as session:
            if number:
                change = session.getChangeByNumber(number)
            elif changeid:
                change = session.getChangeByChangeID(changeid)
            change_key = change and change.key or None
        if change_key is None:
            if self.sync.offline:
                raise Exception('Can not sync change while offline.')
            task = sync.SyncChangeByNumberTask(number or changeid, sync.HIGH_PRIORITY)
            self.sync.submitTask(task)
            succeeded = task.wait(300)
            if not succeeded:
                raise Exception('Unable to find change.')
            for subtask in task.tasks:
                succeeded = subtask.wait(300)
                if not succeeded:
                    raise Exception('Unable to sync change.')
            with self.db.getSession() as session:
                if number:
                    change = session.getChangeByNumber(number)
                elif changeid:
                    change = session.getChangeByChangeID(changeid)
                change_key = change and change.key or None
        if change_key is None:
            raise Exception('Change is not in local database.')

    def doSearch(self, query):
        self.log.debug("Search query: %s" % query)
        try:
            self._syncOneChangeFromQuery(query)
        except Exception as e:
            return self.error(e.message)
        with self.db.getSession() as session:
            try:
                changes = session.getChanges(query)
            except gertty.search.SearchSyntaxError as e:
                return self.error(e.message)
            except sqlalchemy.exc.OperationalError as e:
                return self.error(e.message)
            except Exception as e:
                return self.error(str(e))
            change_key = None
            if len(changes) == 1:
                change_key = changes[0].key
        try:
            if change_key:
                view = view_change.ChangeView(self, change_key)
            else:
                view = view_change_list.ChangeListView(self, query)
            self.changeScreen(view)
        except gertty.view.DisplayError as e:
            return self.error(e.message)

    def searchDialog(self, default):
        dialog = SearchDialog(self, default)
        urwid.connect_signal(dialog, 'cancel',
            lambda button: self.backScreen())
        urwid.connect_signal(dialog, 'search',
            lambda button: self._searchDialog(dialog))
        self.popup(dialog, min_width=76, min_height=8)

    def _searchDialog(self, dialog):
        self.backScreen()
        query = dialog.entry.edit_text.strip()
        if self.simple_change_search.match(query):
            query = 'change:%s' % query
        else:
            result = self.parseInternalURL(query)
            if result is not None:
                return self.openInternalURL(result)
        self.doSearch(query)

    trailing_filename_re = re.compile('.*(,[a-z]+)')
    def parseInternalURL(self, url):
        if not url.startswith(self.config.url):
            return None
        result = urlparse.urlparse(url)
        change = patchset = filename = None
        path = [x for x in result.path.split('/') if x]
        if path:
            change = path[0]
        else:
            path = [x for x in result.fragment.split('/') if x]
            if path[0] == 'c':
                path.pop(0)
            while path:
                if not change:
                    change = path.pop(0)
                    continue
                if not patchset:
                    patchset = path.pop(0)
                    continue
                if not filename:
                    filename = '/'.join(path)
                    m = self.trailing_filename_re.match(filename)
                    if m:
                        filename = filename[:0-len(m.group(1))]
                    path = None
        return (change, patchset, filename)

    def openInternalURL(self, result):
        (change, patchset, filename) = result
        # TODO: support deep-linking to a filename
        self.doSearch('change:%s' % change)

    def error(self, message, title='Error'):
        dialog = mywid.MessageDialog(title, message)
        urwid.connect_signal(dialog, 'close',
                             lambda button: self.backScreen())

        cols, rows = self.loop.screen.get_cols_rows()
        cols = int(cols*.5)
        lines = textwrap.wrap(message, cols)
        min_height = max(4, len(lines)+4)

        self.popup(dialog, min_height=min_height)
        return None

    def unhandledInput(self, key):
        # get commands from buffer
        keys = self.input_buffer + [key]
        commands = self.config.keymap.getCommands(keys)
        if keymap.PREV_SCREEN in commands:
            self.backScreen()
        elif keymap.TOP_SCREEN in commands:
            self.clearHistory()
            self.refresh(force=True)
        elif keymap.HELP in commands:
            self.help()
        elif keymap.QUIT in commands:
            self.quit()
        elif keymap.CHANGE_SEARCH in commands:
            self.searchDialog('')
        elif keymap.LIST_HELD in commands:
            self.doSearch("is:held")
        elif key in self.config.dashboards:
            d = self.config.dashboards[key]
            view = view_change_list.ChangeListView(self, d['query'], d['name'])
            self.changeScreen(view)
        elif keymap.FURTHER_INPUT in commands:
            self.input_buffer.append(key)
            self.status.update(message=''.join(self.input_buffer))
            return
        self.clearInputBuffer()

    def openURL(self, url):
        self.log.debug("Open URL %s" % url)
        webbrowser.open_new_tab(url)
        self.loop.screen.clear()

    def time(self, dt):
        utc = dt.replace(tzinfo=dateutil.tz.tzutc())
        if self.config.utc:
            return utc
        local = utc.astimezone(dateutil.tz.tzlocal())
        return local

    def _errorPipeInput(self, data=None):
        (title, message) = self.error_queue.get()
        self.error(message, title=title)

    def _showWarning(self, message, category, filename, lineno,
                     file=None, line=None):
        # Don't display repeat warnings
        if str(message) in self.logged_warnings:
            return
        m = warnings.formatwarning(message, category, filename, lineno, line)
        self.log.warning(m)
        self.logged_warnings.add(str(message))
        # Log this warning, but never display it to the user; it is
        # nearly un-actionable.
        if category == requestsexceptions.InsecurePlatformWarning:
            return
        # Disable InsecureRequestWarning when certificate validation is disabled
        if not self.config.verify_ssl:
            if category == requestsexceptions.InsecureRequestWarning:
                return
        self.error_queue.put(('Warning', m))
        os.write(self.error_pipe, 'error\n')

    def toggleHeldChange(self, change_key):
        with self.db.getSession() as session:
            change = session.getChange(change_key)
            change.held = not change.held
            ret = change.held
            if not change.held:
                for r in change.revisions:
                    for m in change.messages:
                        if m.pending:
                            self.sync.submitTask(
                                sync.UploadReviewTask(m.key, sync.HIGH_PRIORITY))
        self.updateStatusQueries()
        return ret

    def localCheckoutCommit(self, project_name, commit_sha):
        repo = gitrepo.get_repo(project_name, self.config)
        try:
            repo.checkout(commit_sha)
            dialog = mywid.MessageDialog('Checkout', 'Change checked out in %s' % repo.path)
            min_height=8
        except gitrepo.GitCheckoutError as e:
            dialog = mywid.MessageDialog('Error', e.msg)
            min_height=12
        urwid.connect_signal(dialog, 'close',
            lambda button: self.backScreen())
        self.popup(dialog, min_height=min_height)

    def localCherryPickCommit(self, project_name, commit_sha):
        repo = gitrepo.get_repo(project_name, self.config)
        try:
            repo.cherryPick(commit_sha)
            dialog = mywid.MessageDialog('Cherry-Pick', 'Change cherry-picked in %s' % repo.path)
            min_height=8
        except gitrepo.GitCheckoutError as e:
            dialog = mywid.MessageDialog('Error', e.msg)
            min_height=12
        urwid.connect_signal(dialog, 'close',
            lambda button: self.backScreen())
        self.popup(dialog, min_height=min_height)

    def saveReviews(self, revision_keys, approvals, message, upload, submit):
        message_keys = []
        with self.db.getSession() as session:
            account = session.getAccountByUsername(self.config.username)
            for revision_key in revision_keys:
                k = self._saveReview(session, account, revision_key,
                                     approvals, message, upload, submit)
                if k:
                    message_keys.append(k)
        return message_keys

    def _saveReview(self, session, account, revision_key,
                    approvals, message, upload, submit):
        message_key = None
        revision = session.getRevision(revision_key)
        change = revision.change
        draft_approvals = {}
        for approval in change.draft_approvals:
            draft_approvals[approval.category] = approval

        categories = set()
        for label in change.permitted_labels:
            categories.add(label.category)
        for category in categories:
            value = approvals.get(category, 0)
            approval = draft_approvals.get(category)
            if not approval:
                approval = change.createApproval(account, category, 0, draft=True)
                draft_approvals[category] = approval
            approval.value = value
        draft_message = revision.getPendingMessage()
        if not draft_message:
            draft_message = revision.getDraftMessage()
        if not draft_message:
            if message or upload:
                draft_message = revision.createMessage(None, account,
                                                       datetime.datetime.utcnow(),
                                                       '', draft=True)
        if draft_message:
            draft_message.created = datetime.datetime.utcnow()
            draft_message.message = message
            draft_message.pending = upload
            message_key = draft_message.key
        if upload:
            change.reviewed = True
        if submit:
            change.status = 'SUBMITTED'
            change.pending_status = True
            change.pending_status_message = None
        return message_key



def version():
    return "Gertty version: %s" % gertty.version.version_info.release_string()

class PrintKeymapAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        for cmd in sorted(keymap.DEFAULT_KEYMAP.keys()):
            print cmd.replace(' ', '-')
        sys.exit(0)

class PrintPaletteAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        for attr in sorted(palette.DEFAULT_PALETTE.keys()):
            print attr
        sys.exit(0)

def main():
    parser = argparse.ArgumentParser(
        description='Console client for Gerrit Code Review.')
    parser.add_argument('-c', dest='path',
                        default=config.DEFAULT_CONFIG_PATH,
                        help='path to config file')
    parser.add_argument('-v', dest='verbose', action='store_true',
                        help='enable more verbose logging')
    parser.add_argument('-d', dest='debug', action='store_true',
                        help='enable debug logging')
    parser.add_argument('--no-sync', dest='no_sync', action='store_true',
                        help='disable remote syncing')
    parser.add_argument('--fetch-missing-refs', dest='fetch_missing_refs',
                        action='store_true',
                        help='fetch any refs missing from local repos')
    parser.add_argument('--print-keymap', nargs=0, action=PrintKeymapAction,
                        help='print the keymap command names to stdout')
    parser.add_argument('--print-palette', nargs=0, action=PrintPaletteAction,
                        help='print the palette attribute names to stdout')
    parser.add_argument('--version', dest='version', action='version',
                        version=version(),
                        help='show Gertty\'s version')
    parser.add_argument('-p', dest='palette', default='default',
                        help='color palette to use')
    parser.add_argument('-k', dest='keymap', default='default',
                        help='keymap to use')
    parser.add_argument('server', nargs='?',
                        help='the server to use (as specified in config file)')
    args = parser.parse_args()
    g = App(args.server, args.palette, args.keymap, args.debug, args.verbose,
            args.no_sync, args.fetch_missing_refs, args.path)
    g.run()


if __name__ == '__main__':
    main()
