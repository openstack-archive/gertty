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

GLOBAL_HELP = """\
Global Keys
===========
<F1> or <?> Help
<ESC>       Back to previous screen
<CTRL-Q>    Quit Gertty
"""

class TextButton(urwid.Button):
    def selectable(self):
        return True

    def __init__(self, text, on_press=None, user_data=None):
        super(TextButton, self).__init__('', on_press=on_press, user_data=user_data)
        self.text = urwid.Text(text)
        self._w = urwid.AttrMap(self.text, None, focus_map='focused')

class FixedButton(urwid.Button):
    def sizing(self):
        return frozenset([urwid.FIXED])

    def pack(self, size, focus=False):
        return (len(self.get_label())+4, 1)

class TableColumn(urwid.Pile):
    def pack(self, size, focus=False):
        mx = max([len(i[0].text) for i in self.contents])
        return (mx+2, len(self.contents))

class Table(urwid.WidgetWrap):
    def __init__(self, headers=[], columns=None):
        if columns is None:
            cols = [('pack', TableColumn([('pack', w)])) for w in headers]
        else:
            cols = [('pack', TableColumn([])) for x in range(columns)]
        super(Table, self).__init__(
            urwid.Columns(cols))

    def addRow(self, cells=[]):
        for i, widget in enumerate(cells):
            self._w.contents[i][0].contents.append((widget, ('pack', None)))

class ButtonDialog(urwid.WidgetWrap):
    def __init__(self, title, message, buttons=[]):
        button_widgets = []
        for button in buttons:
            button_widgets.append(('pack', button))
        button_columns = urwid.Columns(button_widgets, dividechars=2)
        rows = []
        rows.append(urwid.Text(message))
        rows.append(urwid.Divider())
        rows.append(button_columns)
        pile = urwid.Pile(rows)
        fill = urwid.Filler(pile, valign='top')
        super(ButtonDialog, self).__init__(urwid.LineBox(fill, title))

class MessageDialog(ButtonDialog):
    signals = ['close']
    def __init__(self, title, message):
        ok_button = FixedButton('OK')
        urwid.connect_signal(ok_button, 'click',
                             lambda button:self._emit('close'))
        super(MessageDialog, self).__init__(title, message, buttons=[ok_button])

class YesNoDialog(ButtonDialog):
    signals = ['yes', 'no']
    def __init__(self, title, message):
        yes_button = FixedButton('Yes')
        no_button = FixedButton('No')
        urwid.connect_signal(yes_button, 'click',
                             lambda button:self._emit('yes'))
        urwid.connect_signal(no_button, 'click',
                             lambda button:self._emit('no'))
        super(YesNoDialog, self).__init__(title, message, buttons=[yes_button,
                                                                   no_button])
    def keypress(self, size, key):
        r = super(YesNoDialog, self).keypress(size, key)
        if r in ('Y', 'y'):
            self._emit('yes')
            return None
        if r in ('N', 'n'):
            self._emit('no')
            return None
        return r
