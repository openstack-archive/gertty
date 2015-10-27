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

from gertty import keymap
from gertty.view import mouse_scroll_decorator

GLOBAL_HELP = (
    (keymap.HELP,
     "Display help"),
    (keymap.PREV_SCREEN,
     "Back to previous screen"),
    (keymap.TOP_SCREEN,
     "Back to project list"),
    (keymap.QUIT,
     "Quit Gertty"),
    (keymap.CHANGE_SEARCH,
     "Search for changes"),
    (keymap.LIST_HELD,
     "List held changes"),
    (keymap.KILL,
     "Kill to end of line (editing)"),
    (keymap.YANK,
     "Yank from kill ring (editing)"),
    (keymap.YANK_POP,
     "Replace previous yank from kill ring (editing)"),
    )

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

class FixedRadioButton(urwid.RadioButton):
    def sizing(self):
        return frozenset([urwid.FIXED])

    def pack(self, size, focus=False):
        return (len(self.get_label())+4, 1)

class TableColumn(urwid.Pile):
    def pack(self, size, focus=False):
        maxcol = size[0]
        mx = max([i[0].pack((maxcol,), focus)[0] for i in self.contents])
        return (min(mx+2, maxcol), len(self.contents))

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

class KillRing(object):
    def __init__(self):
        self.ring = []

    def kill(self, text):
        self.ring.append(text)

    def yank(self, repeat=False):
        if not self.ring:
            return None
        if repeat:
            t = self.ring.pop()
            self.ring.insert(0, t)
        return self.ring[-1]

class MyEdit(urwid.Edit):
    def __init__(self, *args, **kw):
        self.ring = kw.pop('ring', None)
        if not self.ring:
            self.ring = KillRing()
        self.last_yank = None
        super(MyEdit, self).__init__(*args, **kw)

    def keypress(self, size, key):
        (maxcol,) = size
        if self._command_map[key] == keymap.YANK:
            text = self.ring.yank()
            if text:
                self.last_yank = (self.edit_pos, self.edit_pos+len(text))
                self.insert_text(text)
            return
        if self._command_map[key] == keymap.YANK_POP:
            if not self.last_yank:
                return
            text = self.ring.yank(True)
            if text:
                self.edit_text = (self.edit_text[:self.last_yank[0]] +
                                  self.edit_text[self.last_yank[1]:])
                self.last_yank = (self.edit_pos, self.edit_pos+len(text))
                self.insert_text(text)
            return
        self.last_yank = None
        if self._command_map[key] == keymap.KILL:
            text = self.edit_text[self.edit_pos:]
            self.edit_text = self.edit_text[:self.edit_pos]
            self.ring.kill(text)
        return super(MyEdit, self).keypress(size, key)

@mouse_scroll_decorator.ScrollByWheel
class ButtonDialog(urwid.WidgetWrap):
    def __init__(self, title, message, entry_prompt=None,
                 entry_text='', buttons=[], ring=None):
        button_widgets = []
        for button in buttons:
            button_widgets.append(('pack', button))
        button_columns = urwid.Columns(button_widgets, dividechars=2)
        rows = []
        rows.append(urwid.Text(message))
        if entry_prompt:
            self.entry = MyEdit(entry_prompt, edit_text=entry_text, ring=ring)
            rows.append(self.entry)
        else:
            self.entry = None
        rows.append(urwid.Divider())
        rows.append(button_columns)
        listbox = urwid.ListBox(rows)
        super(ButtonDialog, self).__init__(urwid.LineBox(listbox, title))

class TextEditDialog(urwid.WidgetWrap):
    signals = ['save', 'cancel']
    def __init__(self, title, prompt, button, text, ring=None):
        save_button = FixedButton(button)
        cancel_button = FixedButton('Cancel')
        urwid.connect_signal(save_button, 'click',
                             lambda button:self._emit('save'))
        urwid.connect_signal(cancel_button, 'click',
                             lambda button:self._emit('cancel'))
        button_widgets = [('pack', save_button),
                          ('pack', cancel_button)]
        button_columns = urwid.Columns(button_widgets, dividechars=2)
        rows = []
        self.entry = MyEdit(edit_text=text, multiline=True, ring=ring)
        rows.append(urwid.Text(prompt))
        rows.append(self.entry)
        rows.append(urwid.Divider())
        rows.append(button_columns)
        pile = urwid.Pile(rows)
        fill = urwid.Filler(pile, valign='top')
        super(TextEditDialog, self).__init__(urwid.LineBox(fill, title))

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

class SearchableText(urwid.Text):
    def set_text(self, markup):
        self._markup = markup
        super(SearchableText, self).set_text(markup)

    def search(self, search, attribute):
        if not search:
            self.set_text(self._markup)
            return
        (text, attrs) = urwid.util.decompose_tagmarkup(self._markup)
        last = 0
        found = False
        while True:
            start = text.find(search, last)
            if start < 0:
                break
            found = True
            end = start + len(search)
            i = 0
            newattrs = []
            for attr, al in attrs:
                if i + al <= start:
                    i += al
                    newattrs.append((attr, al))
                    continue
                if i >= end:
                    i += al
                    newattrs.append((attr, al))
                    continue
                before = max(start - i, 0)
                after = max(i + al - end, 0)
                if before:
                    newattrs.append((attr, before))
                newattrs.append((attribute, len(search)))
                if after:
                    newattrs.append((attr, after))
                i += al
            if i < start:
                newattrs.append((None, start-i))
                i += start-i
            if i < end:
                newattrs.append((attribute, len(search)))
            last = start + 1
            attrs = newattrs
        self._text = text
        self._attrib = attrs
        self._invalidate()
        return found

class HyperText(urwid.Text):
    _selectable = True

    def __init__(self, markup, align=urwid.LEFT, wrap=urwid.SPACE, layout=None):
        self._mouse_press_item = None
        self.selectable_items = []
        self.focused_index = None
        self.last_focused_index = 0
        super(HyperText, self).__init__(markup, align, wrap, layout)

    def focusFirstItem(self):
        if len(self.selectable_items) == 0:
            return False
        self.focusItem(0)
        return True

    def focusLastItem(self):
        if len(self.selectable_items) == 0:
            return False
        self.focusItem(len(self.selectable_items)-1)
        return True

    def focusPreviousItem(self):
        if len(self.selectable_items) == 0:
            return False
        if self.focused_index is None:
            self.focusItem(self.last_focused_index)
        item = max(0, self.focused_index-1)
        if item != self.focused_index:
            self.focusItem(item)
            return True
        return False

    def focusNextItem(self):
        if len(self.selectable_items) == 0:
            return False
        if self.focused_index is None:
            self.focusItem(self.last_focused_index)
        item = min(len(self.selectable_items)-1, self.focused_index+1)
        if item != self.focused_index:
            self.focusItem(item)
            return True
        return False

    def focusItem(self, item):
        self.last_focused_index = self.focused_index
        self.focused_index = item
        self.set_text(self._markup)
        self._invalidate()

    def select(self):
        if self.focused_index is not None:
            self.selectable_items[self.focused_index][0].select()

    def keypress(self, size, key):
        if self._command_map[key] == urwid.CURSOR_UP:
            if self.focusPreviousItem():
                return False
            return key
        elif self._command_map[key] == urwid.CURSOR_DOWN:
            if self.focusNextItem():
                return False
            return key
        elif self._command_map[key] == urwid.ACTIVATE:
            self.select()
            return False
        return key

    def getPosAtCoords(self, maxcol, col, row):
        trans = self.get_line_translation(maxcol)
        colpos = 0
        line = trans[row]
        for t in line:
            if len(t) == 2:
                width, pos = t
                if colpos <= col < colpos + width:
                    return pos
            else:
                width, start, end = t
                if colpos <= col < colpos + width:
                    return start + (col - colpos)
            colpos += width
        return None

    def getItemAtCoords(self, maxcol, col, row):
        pos = self.getPosAtCoords(maxcol, col, row)
        index = 0
        for item, start, end in self.selectable_items:
            if start <= pos <= end:
                return index
            index += 1
        return None

    def mouse_event(self, size, event, button, col, row, focus):
        if ((button not in [0, 1]) or
            (event not in ['mouse press', 'mouse release'])):
            return False
        item = self.getItemAtCoords(size[0], col, row)
        if item is None:
            if self.focused_index is None:
                self.focusFirstItem()
            return False
        if event == 'mouse press':
            self.focusItem(item)
            self._mouse_press_item = item
        if event == 'mouse release':
            if self._mouse_press_item == item:
                self.select()
            self._mouse_press_item = None
        return True

    def processLinks(self, markup, data=None):
        if data is None:
            data = dict(pos=0)
        if isinstance(markup, list):
            return [self.processLinks(i, data) for i in markup]
        if isinstance(markup, tuple):
            return (markup[0], self.processLinks(markup[1], data))
        if isinstance(markup, Link):
            self.selectable_items.append((markup, data['pos'], data['pos']+len(markup.text)))
            data['pos'] += len(markup.text)
            focused = len(self.selectable_items)-1 == self.focused_index
            link_attr = markup.getAttr(focused)
            if link_attr:
                return (link_attr, markup.text)
            else:
                return markup.text
        data['pos'] += len(markup)
        return markup

    def set_text(self, markup):
        self._markup = markup
        self.selectable_items = []
        super(HyperText, self).set_text(self.processLinks(markup))

    def move_cursor_to_coords(self, size, col, row):
        if self.focused_index is None:
            if row:
                self.focusLastItem()
            else:
                self.focusFirstItem()
        return True

    def render(self, size, focus=False):
        if (not focus) and (self.focused_index is not None):
            self.focusItem(None)
        return super(HyperText, self).render(size, focus)

class Link(urwid.Widget):
    signals = ['selected']

    def __init__(self, text, attr=None, focused_attr=None):
        self.text = text
        self.attr = attr
        self.focused_attr = focused_attr

    def select(self):
        self._emit('selected')

    def getAttr(self, focus):
        if focus:
            return self.focused_attr
        return self.attr

# A workaround for the issue fixed in
# https://github.com/wardi/urwid/pull/74
# included here until thi fix is released
class MyGridFlow(urwid.GridFlow):
    def generate_display_widget(self, size):
        p = super(MyGridFlow, self).generate_display_widget(size)
        for item in p.contents:
            if isinstance(item[0], urwid.Padding):
                c = item[0].original_widget
                if isinstance(c, urwid.Columns):
                    if c.focus_position == 0 and not c.contents[0][0].selectable():
                        for i, w in enumerate(c.contents):
                            if w[0].selectable():
                                c.focus_position = i
                                break
        return p
