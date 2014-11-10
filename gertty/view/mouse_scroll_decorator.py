# coding=utf8
#
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

def mouse_event_scrolling(class_type):
    def mouse_event_scrolling(self, size, event, button, col, row, focus):
        if event == 'mouse press':
            if button == 4:
                self.keypress(size, 'up')
                return True
            if button == 5:
                self.keypress(size, 'down')
                return True

        return super(class_type, self).mouse_event(size, event, button, col,
                                                   row, focus)
    return mouse_event_scrolling

def ScrollByWheel(original_class):
    original_class.mouse_event = mouse_event_scrolling(original_class)
    return original_class
