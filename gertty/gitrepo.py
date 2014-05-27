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

OLD = 0
NEW = 1
START = 0
END = 1
LINENO = 0
LINE = 1

class DiffChunk(object):
    def __init__(self):
        self.oldlines = []
        self.newlines = []
        self.first = False
        self.last = False
        self.lines = []
        self.calcRange()

    def __repr__(self):
        return '<%s old lines %s-%s / new lines %s-%s>' % (
            self.__class__.__name__,
            self.range[OLD][START], self.range[OLD][END],
            self.range[NEW][START], self.range[NEW][END])

    def calcRange(self):
        self.range = [[0, 0],
                      [0, 0]]
        for l in self.lines:
            if self.range[OLD][START] == 0 and l[OLD][LINENO] is not None:
                self.range[OLD][START] = l[OLD][LINENO]
            if self.range[NEW][START] == 0 and l[NEW][LINENO] is not None:
                self.range[NEW][START] = l[NEW][LINENO]
            if (self.range[OLD][START] != 0 and
                self.range[NEW][START] != 0):
                break

        for l in self.lines[::-1]:
            if self.range[OLD][END] == 0 and l[OLD][LINENO] is not None:
                self.range[OLD][END] = l[OLD][LINENO]
            if self.range[NEW][END] == 0 and l[NEW][LINENO] is not None:
                self.range[NEW][END] = l[NEW][LINENO]
            if (self.range[OLD][END] != 0 and
                self.range[NEW][END] != 0):
                break

    def indexOfLine(self, oldnew, lineno):
        for i, l in enumerate(self.lines):
            if l[oldnew][LINENO] == lineno:
                return i

class DiffContextChunk(DiffChunk):
    context = True

class DiffChangedChunk(DiffChunk):
    context = False

class DiffFile(object):
    def __init__(self):
        self.newname = None
        self.oldname = None
        self.chunks = []
        self.current_chunk = None
        self.old_lineno = 0
        self.new_lineno = 0
        self.offset = 0

    def finalize(self):
        if not self.current_chunk:
            return
        self.current_chunk.lines = zip(self.current_chunk.oldlines,
                                       self.current_chunk.newlines)
        if not self.chunks:
            self.current_chunk.first = True
        else:
            self.chunks[-1].last = False
        self.current_chunk.last = True
        self.current_chunk.calcRange()
        self.chunks.append(self.current_chunk)
        self.current_chunk = None

    def addDiffLines(self, old, new):
        if (self.current_chunk and
            not isinstance(self.current_chunk, DiffChangedChunk)):
            self.finalize()
        if not self.current_chunk:
            self.current_chunk = DiffChangedChunk()
        for l in old:
            self.current_chunk.oldlines.append((self.old_lineno, '-', l))
            self.old_lineno += 1
            self.offset -= 1
        for l in new:
            self.current_chunk.newlines.append((self.new_lineno, '+', l))
            self.new_lineno += 1
            self.offset += 1
        while self.offset > 0:
            self.current_chunk.oldlines.append((None, '', ''))
            self.offset -= 1
        while self.offset < 0:
            self.current_chunk.newlines.append((None, '', ''))
            self.offset += 1

    def addNewLine(self, line):
        if (self.current_chunk and
            not isinstance(self.current_chunk, DiffChangedChunk)):
            self.finalize()
        if not self.current_chunk:
            self.current_chunk = DiffChangedChunk()

    def addContextLine(self, line):
        if (self.current_chunk and
            not isinstance(self.current_chunk, DiffContextChunk)):
            self.finalize()
        if not self.current_chunk:
            self.current_chunk = DiffContextChunk()
        self.current_chunk.oldlines.append((self.old_lineno, ' ', line))
        self.current_chunk.newlines.append((self.new_lineno, ' ', line))
        self.old_lineno += 1
        self.new_lineno += 1

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

    def cherryPick(self, ref):
        repo = git.Repo(self.path)
        try:
            repo.git.cherry_pick(ref)
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

    def intralineDiff(self, old, new):
        # takes a list of old lines and a list of new lines
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
    def diff(self, old, new, context=10000):
        repo = git.Repo(self.path)
        #'-y', '-x', 'diff -C10', old, new, path).split('\n'):
        oldc = repo.commit(old)
        newc = repo.commit(new)
        files = []
        for diff_context in oldc.diff(newc, create_patch=True, U=context):
            # Each iteration of this is a file
            f = DiffFile()
            files.append(f)
            if diff_context.rename_from:
                f.oldname = diff_context.rename_from
            if diff_context.rename_to:
                f.newname = diff_context.rename_to
            oldchunk = []
            newchunk = []
            prev_key = ''
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
                    f.old_lineno = int(m.group(1))
                    f.new_lineno = int(m.group(3))
                    continue
                if not line:
                    if prev_key != '\\':
                        # Strangely, we get an extra newline in the
                        # diff in the case that the last line is "\ No
                        # newline at end of file".  This is a
                        # workaround for that.
                        prev_key = ''
                        line = 'X '
                    else:
                        line = ' '
                key = line[0]
                rest = line[1:]
                if key == '\\':
                    # This is for "\ No newline at end of file" which
                    # follows either a -, + or ' ' line to indicate
                    # which file it's talking about (or both).  For
                    # now, treat it like normal text and let the user
                    # infer from context that it's not actually in the
                    # file.  Potential TODO: highlight it to make that
                    # more clear.
                    if prev_key:
                        key = prev_key
                    else:
                        key = ' '
                    prev_key = '\\'
                if key == '-':
                    prev_key = '-'
                    oldchunk.append(rest)
                    if not last_line:
                        continue
                if key == '+':
                    prev_key = '+'
                    newchunk.append(rest)
                    if not last_line:
                        continue
                prev_key = ''
                # end of chunk
                if oldchunk or newchunk:
                    oldchunk, newchunk = self.intralineDiff(oldchunk, newchunk)
                    f.addDiffLines(oldchunk, newchunk)
                oldchunk = []
                newchunk = []
                if key == ' ':
                    f.addContextLine(rest)
                    continue
                if line.startswith("similarity index"):
                    continue
                if line.startswith("rename"):
                    continue
                if line.startswith("index"):
                    continue
                if not last_line:
                    raise Exception("Unhandled line: %s" % line)
            f.finalize()
        return files
