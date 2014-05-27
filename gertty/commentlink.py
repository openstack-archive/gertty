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

import re

class TextReplacement(object):
    def __init__(self, config):
        if isinstance(config, basestring):
            self.color = None
            self.text = config
        else:
            self.color = config.get('color')
            self.text = config['text']

    def replace(self, data):
        if self.color:
            return (self.color.format(**data), self.text.format(**data))
        return (None, self.text.format(**data))

class CommentLink(object):
    def __init__(self, config):
        self.match = re.compile(config['match'], re.M)
        self.replacements = []
        for r in config['replacements']:
            if 'text' in r:
                self.replacements.append(TextReplacement(r['text']))

    def run(self, chunks):
        ret = []
        for chunk in chunks:
            if not isinstance(chunk, basestring):
                # We don't currently support nested commentlinks; if
                # we have something that isn't a string, just append
                # it to the output.
                ret.append(chunk)
                continue
            if not chunk:
                ret += [chunk]
            while chunk:
                m = self.match.search(chunk)
                if not m:
                    ret.append(chunk)
                    break
                before = chunk[:m.start()]
                after = chunk[m.end():]
                if before:
                    ret.append(before)
                ret += [r.replace(m.groupdict()) for r in self.replacements]
                chunk = after
        return ret

