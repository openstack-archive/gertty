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

import argparse
import logging
import os
import sys
import threading

import urwid

from gertty import db
from gertty import config
from gertty import gitrepo
from gertty import mywid
from gertty import sync
from gertty.view import project_list as view_project_list
from gertty.view import change as view_change

WELCOME_TEXT = """\
Welcome to Gertty!

To get started, you should subscribe to some projects.  Press the "l"
key to list all the projects, navigate to the ones you are interested
in, and then press "s" to subscribe to them.  Gertty will
automatically sync changes in your subscribed projects.

Press the F1 key anywhere to get help.  Your terminal emulator may
require you to press function-F1 or alt-F1 instead.

"""

class StatusHeader(urwid.WidgetWrap):
    def __init__(self, app):
        super(StatusHeader, self).__init__(urwid.Columns([]))
        self.app = app
        self.title = urwid.Text(u'Start')
        self.error = urwid.Text('')
        self.offline = urwid.Text('')
        self.sync = urwid.Text(u'Sync: 0')
        self._w.contents.append((self.title, ('pack', None, False)))
        self._w.contents.append((urwid.Text(u''), ('weight', 1, False)))
        self._w.contents.append((self.error, ('pack', None, False)))
        self._w.contents.append((self.offline, ('pack', None, False)))
        self._w.contents.append((self.sync, ('pack', None, False)))

    def update(self, title=None, error=False, offline=None):
        if title:
            self.title.set_text(title)
        if error:
            self.error.set_text(('error', u'Error'))
        if offline is not None:
            if offline:
                self.error.set_text(u'Offline')
            else:
                self.error.set_text(u'')
        self.sync.set_text(u' Sync: %i' % self.app.sync.queue.qsize())

class OpenChangeDialog(mywid.ButtonDialog):
    signals = ['open', 'cancel']
    def __init__(self):
        open_button = mywid.FixedButton('Open')
        cancel_button = mywid.FixedButton('Cancel')
        urwid.connect_signal(open_button, 'click',
                             lambda button:self._emit('open'))
        urwid.connect_signal(cancel_button, 'click',
                             lambda button:self._emit('cancel'))
        super(OpenChangeDialog, self).__init__("Open Change",
                                               "Enter a change number to open that change.",
                                               entry_prompt="Number: ",
                                               buttons=[open_button,
                                                        cancel_button])

    def keypress(self, size, key):
        r = super(OpenChangeDialog, self).keypress(size, key)
        if r == 'enter':
            self._emit('open')
            return None
        return r

class App(object):
    def __init__(self, server=None, palette='default', debug=False, disable_sync=False):
        self.server = server
        self.config = config.Config(server, palette)
        if debug:
            level = logging.DEBUG
        else:
            level = logging.WARNING
        logging.basicConfig(filename=self.config.log_file, filemode='w',
                            format='%(asctime)s %(message)s',
                            level=level)
        self.log = logging.getLogger('gertty.App')
        self.log.debug("Starting")
        self.db = db.Database(self)
        self.sync = sync.Sync(self)

        self.screens = []
        self.status = StatusHeader(self)
        self.header = urwid.AttrMap(self.status, 'header')
        screen = view_project_list.ProjectListView(self)
        self.status.update(title=screen.title)
        self.loop = urwid.MainLoop(screen, palette=self.config.palette.getPalette(),
                                   unhandled_input=self.unhandledInput)
        if screen.isEmpty():
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
        self.loop.run()

    def _quit(self, widget=None):
        raise urwid.ExitMainLoop()

    def quit(self):
        dialog = mywid.YesNoDialog(u'Quit',
                                   u'Are you sure you want to quit?')
        urwid.connect_signal(dialog, 'no', self.backScreen)
        urwid.connect_signal(dialog, 'yes', self._quit)

        self.popup(dialog)

    def changeScreen(self, widget):
        self.log.debug("Changing screen to %s" % (widget,))
        self.status.update(title=widget.title)
        self.screens.append(self.loop.widget)
        self.loop.widget = widget

    def backScreen(self, widget=None):
        if not self.screens:
            return
        widget = self.screens.pop()
        self.log.debug("Popping screen to %s" % (widget,))
        if hasattr(widget, 'title'):
            self.status.update(title=widget.title)
        self.loop.widget = widget
        self.refresh()

    def refresh(self, data=None):
        widget = self.loop.widget
        while isinstance(widget, urwid.Overlay):
            widget = widget.contents[0][0]
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
        dialog = mywid.MessageDialog('Help', self.loop.widget.help)
        lines = self.loop.widget.help.split('\n')
        urwid.connect_signal(dialog, 'close',
            lambda button: self.backScreen())
        self.popup(dialog, min_width=76, min_height=len(lines)+4)

    def welcome(self):
        text = WELCOME_TEXT + self.loop.widget.help
        dialog = mywid.MessageDialog('Welcome', text)
        lines = text.split('\n')
        urwid.connect_signal(dialog, 'close',
            lambda button: self.backScreen())
        self.popup(dialog, min_width=76, min_height=len(lines)+4)

    def openChange(self):
        dialog = OpenChangeDialog()
        urwid.connect_signal(dialog, 'cancel',
            lambda button: self.backScreen())
        urwid.connect_signal(dialog, 'open',
            lambda button: self._openChange(dialog))
        self.popup(dialog, min_width=76, min_height=8)

    def _openChange(self, open_change_dialog):
        self.backScreen()
        number = open_change_dialog.entry.edit_text
        try:
            number = int(number)
        except Exception:
            return self.error('Change number must be an integer.')
        with self.db.getSession() as session:
            change = session.getChangeByNumber(number)
            change_key = change and change.key or None
        if change_key is None:
            if self.sync.offline:
                return self.error('Can not sync change while offline.')
            task = sync.SyncChangeByNumberTask(number, sync.HIGH_PRIORITY)
            self.sync.submitTask(task)
            succeeded = task.wait(300)
            if not succeeded:
                return self.error('Unable to find change.')
            for subtask in task.tasks:
                succeeded = task.wait(300)
                if not succeeded:
                    return self.error('Unable to sync change.')
            with self.db.getSession() as session:
                change = session.getChangeByNumber(number)
                change_key = change and change.key or None
        if change_key is None:
            return self.error('Change is not in local database.')
        self.changeScreen(view_change.ChangeView(self, change_key))

    def error(self, message):
        dialog = mywid.MessageDialog('Error', message)
        urwid.connect_signal(dialog, 'close',
                             lambda button: self.backScreen())
        self.popup(dialog, min_height=4)
        return None

    def unhandledInput(self, key):
        if key == 'esc':
            self.backScreen()
        elif key == 'f1' or key == '?':
            self.help()
        elif key == 'ctrl q':
            self.quit()
        elif key == 'ctrl o':
            self.openChange()

    def getRepo(self, project_name):
        local_path = os.path.join(self.config.git_root, project_name)
        local_root = os.path.abspath(self.config.git_root)
        assert os.path.commonprefix((local_root, local_path)) == local_root
        return gitrepo.Repo(self.config.url+'p/'+project_name,
                            local_path)


def main():
    parser = argparse.ArgumentParser(
        description='Console client for Gerrit Code Review.')
    parser.add_argument('-d', dest='debug', action='store_true',
                        help='enable debug logging')
    parser.add_argument('--no-sync', dest='no_sync', action='store_true',
                        help='disable remote syncing')
    parser.add_argument('-p', dest='palette', default='default',
                        help='Color palette to use')
    parser.add_argument('server', nargs='?',
                        help='the server to use (as specified in config file)')
    args = parser.parse_args()
    g = App(args.server, args.palette, args.debug, args.no_sync)
    g.run()


if __name__ == '__main__':
    main()
