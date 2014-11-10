# Copyright 2014 Jan Kundrát <jkt@kde.org>
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

def mouse_event(self, size, event, button, col, row, focus):
    if event == 'mouse press':
        if button == 4:
            self._scroll_recipient.keypress(size, 'up')
            return True
        if button == 5:
            self._scroll_recipient.keypress(size, 'down')
            return True

    return super(type(self), self).mouse_event(size, event, button, col, row,
                                               focus)

def ScrollWheelListbox(original_class):
    _ScrollWheelListbox_orig_init = original_class.__init__

    def __init__(self, *args, **kwargs):
        _ScrollWheelListbox_orig_init(self, *args, **kwargs)
        self._scroll_recipient = self.listbox

    original_class.__init__ = __init__
    original_class.mouse_event = mouse_event
    return original_class
