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

import logging
import difflib
import os
import re

import git

class DiffFile(object):
    def __init__(self):
        self.newname = None
        self.oldname = None
        self.oldlines = []
        self.newlines = []

class GitCheckoutError(Exception):
    def __init__(self, msg):
        super(GitCheckoutError, self).__init__(msg)
        self.msg = msg

class Repo(object):
    def __init__(self, url, path):
        self.log = logging.getLogger('gertty.gitrepo')
        self.url = url
        self.path = path
        self.differ = difflib.Differ()
        if not os.path.exists(path):
            git.Repo.clone_from(self.url, self.path)

    def fetch(self, url, refspec):
        repo = git.Repo(self.path)
        try:
            repo.git.fetch(url, refspec)
        except AssertionError:
            repo.git.fetch(url, refspec)

    def checkout(self, ref):
        repo = git.Repo(self.path)
        try:
            repo.git.checkout(ref)
        except git.exc.GitCommandError as e:
            raise GitCheckoutError(e.stderr.replace('\t', '    '))

    def diffstat(self, old, new):
        repo = git.Repo(self.path)
        diff = repo.git.diff('-M', '--numstat', old, new)
        ret = []
        for x in diff.split('\n'):
            # Added, removed, filename
            ret.append(x.split('\t'))
        return ret

    def intraline_diff(self, old, new):
        prevline = None
        prevstyle = None
        output_old = []
        output_new = []
        #socket.send('startold' + repr(old)+'\n')
        #socket.send('startnew' + repr(new)+'\n')
        for line in self.differ.compare(old, new):
            #socket.sendall('diff output: ' + line+'\n')
            key = line[0]
            rest = line[2:]
            if key == '?':
                result = []
                accumulator = ''
                emphasis = False
                rest = rest[:-1]  # It has a newline.
                for i, c in enumerate(prevline):
                    if i >= len(rest):
                        indicator = ' '
                    else:
                        indicator = rest[i]
                    #socket.sendall('%s %s %s %s %s\n' % (i, c, indicator, emphasis, accumulator))
                    if indicator != ' ' and not emphasis:
                        # changing from not emph to emph
                        if accumulator:
                            result.append((prevstyle+'-line', accumulator))
                        accumulator = ''
                        emphasis = True
                    elif indicator == ' ' and emphasis:
                        # changing from emph to not emph
                        if accumulator:
                            result.append((prevstyle+'-word', accumulator))
                        accumulator = ''
                        emphasis = False
                    accumulator += c
                if accumulator:
                    if emphasis:
                        result.append((prevstyle+'-word', accumulator))
                    else:
                        result.append((prevstyle+'-line', accumulator))
                if prevstyle == 'added':
                    output_new.append(result)
                elif prevstyle == 'removed':
                    output_old.append(result)
                prevline = None
                continue
            if prevline is not None:
                if prevstyle == 'added':
                    output_new.append((prevstyle+'-line', prevline))
                elif prevstyle == 'removed':
                    output_old.append((prevstyle+'-line', prevline))
            if key == '+':
                prevstyle = 'added'
            elif key == '-':
                prevstyle = 'removed'
            prevline = rest
        #socket.sendall('prev'+repr(prevline)+'\n')
        if prevline is not None:
            if prevstyle == 'added':
                output_new.append((prevstyle+'-line', prevline))
            elif prevstyle == 'removed':
                output_old.append((prevstyle+'-line', prevline))
        #socket.sendall(repr(output_old)+'\n')
        #socket.sendall(repr(output_new)+'\n')
        #socket.sendall('\n')
        return output_old, output_new

    header_re = re.compile('@@ -(\d+)(,\d+)? \+(\d+)(,\d+)? @@')
    def diff(self, old, new, context=20):
        repo = git.Repo(self.path)
        #'-y', '-x', 'diff -C10', old, new, path).split('\n'):
        oldc = repo.commit(old)
        newc = repo.commit(new)
        files = []
        for diff_context in oldc.diff(newc, create_patch=True, U=context):
            f = DiffFile()
            files.append(f)
            old_lineno = 0
            new_lineno = 0
            offset = 0
            oldchunk = []
            newchunk = []
            diff_lines = diff_context.diff.split('\n')
            for i, line in enumerate(diff_lines):
                last_line = (i == len(diff_lines)-1)
                if line.startswith('---'):
                    f.oldname = line[6:]
                    if line[4:] == '/dev/null':
                        f.oldname = 'Empty file'
                    continue
                if line.startswith('+++'):
                    f.newname = line[6:]
                    if line[4:] == '/dev/null':
                        f.newname = 'Empty file'
                    continue
                if line.startswith('@@'):
                    #socket.sendall(line)
                    m = self.header_re.match(line)
                    #socket.sendall(str(m.groups()))
                    old_lineno = int(m.group(1))
                    new_lineno = int(m.group(3))
                    continue
                if not line:
                    line = ' '
                key = line[0]
                rest = line[1:]
                if key == '-':
                    oldchunk.append(rest)
                    if not last_line:
                        continue
                if key == '+':
                    newchunk.append(rest)
                    if not last_line:
                        continue
                # end of chunk
                if oldchunk or newchunk:
                    oldchunk, newchunk = self.intraline_diff(oldchunk, newchunk)
                for l in oldchunk:
                    f.oldlines.append((old_lineno, '-', l))
                    old_lineno += 1
                    offset -= 1
                for l in newchunk:
                    f.newlines.append((new_lineno, '+', l))
                    new_lineno += 1
                    offset += 1
                oldchunk = []
                newchunk = []
                while offset > 0:
                    f.oldlines.append((None, '', ''))
                    offset -= 1
                while offset < 0:
                    f.newlines.append((None, '', ''))
                    offset += 1
                if key == ' ':
                    f.oldlines.append((old_lineno, ' ', rest))
                    f.newlines.append((new_lineno, ' ', rest))
                    old_lineno += 1
                    new_lineno += 1
                    continue
                if not last_line:
                    raise Exception("Unhandled line: %s" % line)
        return files
