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
import logging
import os
import Queue
import sys
import threading
import webbrowser

import urwid

from gertty import db
from gertty import config
from gertty import gitrepo
from gertty import keymap
from gertty import mywid
from gertty import palette
from gertty import sync
from gertty import search
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
        self._w.contents.append((self.title_widget, ('pack', None, False)))
        self._w.contents.append((urwid.Text(u''), ('weight', 1, False)))
        self._w.contents.append((self.error_widget, ('pack', None, False)))
        self._w.contents.append((self.offline_widget, ('pack', None, False)))
        self._w.contents.append((self.sync_widget, ('pack', None, False)))
        self.error = None
        self.offline = None
        self.title = None
        self.sync = None
        self._error = False
        self._offline = False
        self._title = ''
        self._sync = 0

    def update(self, title=None, error=None, offline=None, refresh=True):
        if title is not None:
            self.title = title
        if error is not None:
            self.error = error
        if offline is not None:
            self.offline = offline
        self.sync = self.app.sync.queue.qsize()
        if refresh:
            self.refresh()

    def refresh(self):
        if self._title != self.title:
            self._title = self.title
            self.title_widget.set_text(self._title)
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
    def __init__(self, app):
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
                                           buttons=[search_button,
                                                    cancel_button])

    def keypress(self, size, key):
        r = super(SearchDialog, self).keypress(size, key)
        commands = self.app.config.keymap.getCommands(r)
        if keymap.ACTIVATE in commands:
            self._emit('search')
            return None
        return r

class App(object):
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

        self.fetch_missing_refs = fetch_missing_refs
        self.config.keymap.updateCommandMap()
        self.search = search.SearchCompiler(self)
        self.db = db.Database(self)
        self.sync = sync.Sync(self)

        self.screens = []
        self.status = StatusHeader(self)
        self.header = urwid.AttrMap(self.status, 'header')
        screen = view_project_list.ProjectListView(self)
        self.status.update(title=screen.title)
        self.loop = urwid.MainLoop(screen, palette=self.config.palette.getPalette(),
                                   unhandled_input=self.unhandledInput)

        has_subscribed_projects = False
        with self.db.getSession() as session:
            if session.getProjects(subscribed=True):
                has_subscribed_projects = True
        if not has_subscribed_projects:
            self.welcome()

        self.sync_pipe = self.loop.watch_pipe(self.refresh)
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

    def changeScreen(self, widget, push=True):
        self.log.debug("Changing screen to %s" % (widget,))
        self.status.update(error=False, title=widget.title)
        if push:
            self.screens.append(self.loop.widget)
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
            self.loop.widget = widget

    def refresh(self, data=None, force=False):
        self.status.refresh()
        widget = self.loop.widget
        while isinstance(widget, urwid.Overlay):
            widget = widget.contents[0][0]
        interested = force
        try:
            while True:
                event = self.sync.result_queue.get(0)
                if widget.interested(event):
                    interested = True
        except Queue.Empty:
            pass
        if interested:
            widget.refresh()

    def popup(self, widget,
              relative_width=50, relative_height=25,
              min_width=20, min_height=8):
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

    def searchDialog(self):
        dialog = SearchDialog(self)
        urwid.connect_signal(dialog, 'cancel',
            lambda button: self.backScreen())
        urwid.connect_signal(dialog, 'search',
            lambda button: self._searchDialog(dialog))
        self.popup(dialog, min_width=76, min_height=8)

    def _searchDialog(self, dialog):
        self.backScreen()
        query = dialog.entry.edit_text
        try:
            query = 'change:%s' % int(query)
        except ValueError:
            pass
        self.doSearch(query)

    def error(self, message):
        dialog = mywid.MessageDialog('Error', message)
        urwid.connect_signal(dialog, 'close',
                             lambda button: self.backScreen())
        self.popup(dialog, min_height=4)
        return None

    def unhandledInput(self, key):
        commands = self.config.keymap.getCommands(key)
        if keymap.PREV_SCREEN in commands:
            self.backScreen()
        elif keymap.HELP in commands:
            self.help()
        elif keymap.QUIT in commands:
            self.quit()
        elif keymap.CHANGE_SEARCH in commands:
            self.searchDialog()
        elif key in self.config.dashboards:
            d = self.config.dashboards[key]
            self.clearHistory()
            view = view_change_list.ChangeListView(self, d['query'], d['name'])
            self.changeScreen(view)

    def getRepo(self, project_name):
        local_path = os.path.join(self.config.git_root, project_name)
        local_root = os.path.abspath(self.config.git_root)
        assert os.path.commonprefix((local_root, local_path)) == local_root
        return gitrepo.Repo(self.config.url+'p/'+project_name,
                            local_path)

    def openURL(self, url):
        self.log.debug("Open URL %s" % url)
        webbrowser.open_new_tab(url)

def version():
    return "Gertty version: %s" % gertty.version.version_info.version_string()

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
