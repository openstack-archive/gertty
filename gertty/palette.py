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

DEFAULT_PALETTE={
    'focused': ['default,standout', ''],
    'header': ['white,bold', 'dark blue'],
    'error': ['light red', 'dark blue'],
    'table-header': ['white,bold', ''],
    'filename': ['light cyan', ''],
    'focused-filename': ['light cyan,standout', ''],
    'positive-label': ['dark green', ''],
    'negative-label': ['dark red', ''],
    'max-label': ['light green', ''],
    'min-label': ['light red', ''],
    'focused-positive-label': ['dark green,standout', ''],
    'focused-negative-label': ['dark red,standout', ''],
    'focused-max-label': ['light green,standout', ''],
    'focused-min-label': ['light red,standout', ''],
    'link': ['dark blue', ''],
    'focused-link': ['light blue', ''],
    # Diff
    'context-button': ['dark magenta', ''],
    'focused-context-button': ['light magenta', ''],
    'removed-line': ['dark red', ''],
    'removed-word': ['light red', ''],
    'added-line': ['dark green', ''],
    'added-word': ['light green', ''],
    'nonexistent': ['default', ''],
    'focused-removed-line': ['dark red,standout', ''],
    'focused-removed-word': ['light red,standout', ''],
    'focused-added-line': ['dark green,standout', ''],
    'focused-added-word': ['light green,standout', ''],
    'focused-nonexistent': ['default,standout', ''],
    'draft-comment': ['default', 'dark gray'],
    'comment': ['light gray', 'dark gray'],
    'comment-name': ['white', 'dark gray'],
    'line-number': ['dark gray', ''],
    'focused-line-number': ['dark gray,standout', ''],
    'search-result': ['default,standout', ''],
    # Change view
    'change-data': ['dark cyan', ''],
    'focused-change-data': ['light cyan', ''],
    'change-header': ['light blue', ''],
    'revision-name': ['light blue', ''],
    'revision-commit': ['dark blue', ''],
    'revision-comments': ['default', ''],
    'revision-drafts': ['dark red', ''],
    'focused-revision-name': ['light blue,standout', ''],
    'focused-revision-commit': ['dark blue,standout', ''],
    'focused-revision-comments': ['default,standout', ''],
    'focused-revision-drafts': ['dark red,standout', ''],
    'change-message-name': ['yellow', ''],
    'change-message-own-name': ['light cyan', ''],
    'change-message-header': ['brown', ''],
    'change-message-own-header': ['dark cyan', ''],
    'change-message-draft': ['dark red', ''],
    'revision-button': ['dark magenta', ''],
    'focused-revision-button': ['light magenta', ''],
    'lines-added': ['light green', ''],
    'lines-removed': ['light red', ''],
    'reviewer-name': ['yellow', ''],
    'reviewer-own-name': ['light cyan', ''],
    # project list
    'unreviewed-project': ['white', ''],
    'subscribed-project': ['default', ''],
    'unsubscribed-project': ['dark gray', ''],
    'focused-unreviewed-project': ['white,standout', ''],
    'focused-subscribed-project': ['default,standout', ''],
    'focused-unsubscribed-project': ['dark gray,standout', ''],
    # change list
    'unreviewed-change': ['default', ''],
    'reviewed-change': ['dark gray', ''],
    'focused-unreviewed-change': ['default,standout', ''],
    'focused-reviewed-change': ['dark gray,standout', ''],
    'starred-change': ['light cyan', ''],
    'focused-starred-change': ['light cyan,standout', ''],
    'held-change': ['light red', ''],
    'focused-held-change': ['light red,standout', ''],
    'marked-change': ['dark cyan', ''],
    'focused-marked-change': ['dark cyan,standout', ''],
    }

# A delta from the default palette
LIGHT_PALETTE = {
    'table-header': ['black,bold', ''],
    'unreviewed-project': ['black', ''],
    'subscribed-project': ['dark gray', ''],
    'unsubscribed-project': ['dark gray', ''],
    'focused-unreviewed-project': ['black,standout', ''],
    'focused-subscribed-project': ['dark gray,standout', ''],
    'focused-unsubscribed-project': ['dark gray,standout', ''],
    'change-data': ['dark blue,bold', ''],
    'focused-change-data': ['dark blue,standout', ''],
    'reviewer-name': ['brown', ''],
    'reviewer-own-name': ['dark blue,bold', ''],
    'change-message-name': ['brown', ''],
    'change-message-own-name': ['dark blue,bold', ''],
    'change-message-header': ['black', ''],
    'change-message-own-header': ['black,bold', ''],
    'focused-link': ['dark blue,bold', ''],
    'filename': ['dark cyan', ''],
    }

class Palette(object):
    def __init__(self, config):
        self.palette = {}
        self.palette.update(DEFAULT_PALETTE)
        self.update(config)

    def update(self, config):
        d = config.copy()
        if 'name' in d:
            del d['name']
        self.palette.update(d)

    def getPalette(self):
        ret = []
        for k,v in self.palette.items():
            ret.append(tuple([k]+v))
        return ret
