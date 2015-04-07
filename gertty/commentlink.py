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

import collections
try:
    import ordereddict
except:
    pass
import re

import urwid

import mywid

try:
    OrderedDict = collections.OrderedDict
except AttributeError:
    OrderedDict = ordereddict.OrderedDict

class TextReplacement(object):
    def __init__(self, config):
        if isinstance(config, basestring):
            self.color = None
            self.text = config
        else:
            self.color = config.get('color')
            self.text = config['text']

    def replace(self, app, data):
        if self.color:
            return (self.color.format(**data), self.text.format(**data))
        return (None, self.text.format(**data))

class LinkReplacement(object):
    def __init__(self, config):
        self.url = config['url']
        self.text = config['text']

    def replace(self, app, data):
        link = mywid.Link(self.text.format(**data), 'link', 'focused-link')
        urwid.connect_signal(link, 'selected',
            lambda link:self.activate(app, self.url.format(**data)))
        return link

    def activate(self, app, url):
        result = app.parseInternalURL(url)
        if result is not None:
            return app.openInternalURL(result)
        return app.openURL(url)

class SearchReplacement(object):
    def __init__(self, config):
        self.query = config['query']
        self.text = config['text']

    def replace(self, app, data):
        link = mywid.Link(self.text.format(**data), 'link', 'focused-link')
        urwid.connect_signal(link, 'selected',
            lambda link:app.doSearch(self.query.format(**data)))
        return link

class CommentLink(object):
    def __init__(self, config):
        self.match = re.compile(config['match'], re.M)
        self.test_result = config.get('test-result', None)
        self.replacements = []
        for r in config['replacements']:
            if 'text' in r:
                self.replacements.append(TextReplacement(r['text']))
            if 'link' in r:
                self.replacements.append(LinkReplacement(r['link']))
            if 'search' in r:
                self.replacements.append(SearchReplacement(r['search']))

    def getTestResults(self, app, text):
        if self.test_result is None:
            return {}
        ret = OrderedDict()
        for line in text.split('\n'):
            m = self.match.search(line)
            if m:
                repl = [r.replace(app, m.groupdict()) for r in self.replacements]
                job = self.test_result.format(**m.groupdict())
                ret[job] = repl + ['\n']
        return ret

    def run(self, app, chunks):
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
                ret += [r.replace(app, m.groupdict()) for r in self.replacements]
                chunk = after
        return ret

