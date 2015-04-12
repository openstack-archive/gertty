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

import datetime
import logging
import difflib
import itertools
import os
import re

import git
import gitdb

OLD = 0
NEW = 1
START = 0
END = 1
LINENO = 0
LINE = 1

class GitTimeZone(datetime.tzinfo):
    """Because we can't have nice things."""

    def __init__(self, offset_seconds):
        self._offset = offset_seconds

    def utcoffset(self, dt):
        return datetime.timedelta(seconds=self._offset)

    def dst(self, dt):
        return datetime.timedelta(0)

    def tzname(self, dt):
        return None


class CommitBlob(object):
    def __init__(self):
        self.path = '/COMMIT_MSG'


class CommitContext(object):
    """A git.diff.Diff for commit messages."""

    def decorateGitTime(self, seconds, tz):
        dt = datetime.datetime.fromtimestamp(seconds, GitTimeZone(-tz))
        return dt.strftime('%Y-%m-%d %H:%M:%S %Z%z')

    def decorateMessage(self, commit):
        """Put the Gerrit commit metadata at the front of the message.

        e.g.:
            Parent: cc8a51ca (Initial commit)           1
            Author: Robert Collins <rbtcollins@hp.com>  2
            AuthorDate: 2014-05-27 14:05:47 +1200       3
            Commit: Robert Collins <rbtcollins@hp.com>  4
            CommitDate: 2014-05-27 14:07:57 +1200       5
                                                        6
        """
        # NB: If folk report that commits have comments at the wrong place
        # Then this function, which reproduces gerrit behaviour, will need
        # to be fixed (e.g. by making the behaviour match more closely.
        if not commit:
            return []
        if commit.parents:
            parentsha = commit.parents[0].hexsha[:8]
        else:
            parentsha = None
        author = commit.author
        committer = commit.committer
        author_date = self.decorateGitTime(
            commit.authored_date, commit.author_tz_offset)
        commit_date = self.decorateGitTime(
            commit.committed_date, commit.committer_tz_offset)
        if type(author.email) is unicode:
            author_email = author.email
        else:
            author_email = unicode(author.email, 'utf8')
        if type(committer.email) is unicode:
            committer_email = committer.email
        else:
            committer_email = unicode(committer.email, 'utf8')
        return [u"Parent: %s\n" % parentsha,
                u"Author: %s <%s>\n" % (author.name, author_email),
                u"AuthorDate: %s\n" % author_date,
                u"Commit: %s <%s>\n" % (committer.name, committer_email),
                u"CommitDate: %s\n" % commit_date,
                u"\n"] + commit.message.splitlines(True)

    def __init__(self, old, new):
        """Create a CommitContext.

        :param old: A git.objects.commit object or None.
        :param new: A git.objects.commit object.
        """
        self.rename_from = self.rename_to = None
        if old is None:
            self.new_file = True
        else:
            self.new_file = False
        self.deleted_file = False
        self.a_blob = CommitBlob()
        self.b_blob = CommitBlob()
        self.a_path = self.a_blob.path
        self.b_path = self.b_blob.path
        self.diff = ''.join(difflib.unified_diff(
            self.decorateMessage(old), self.decorateMessage(new),
            fromfile="/a/COMMIT_MSG", tofile="/b/COMMIT_MSG"))


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
        self.newname = 'Unknown File'
        self.oldname = 'Unknown File'
        self.old_empty = False
        self.new_empty = False
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

class GitCloneError(Exception):
    def __init__(self, msg):
        super(GitCloneError, self).__init__(msg)
        self.msg = msg

class Repo(object):
    def __init__(self, url, path):
        self.log = logging.getLogger('gertty.gitrepo')
        self.url = url
        self.path = path
        self.differ = difflib.Differ()
        if not os.path.exists(path):
            if url is None:
                raise GitCloneError("No URL available for git clone")
            git.Repo.clone_from(self.url, self.path)

    def hasCommit(self, sha):
        repo = git.Repo(self.path)
        try:
            repo.commit(sha)
        except gitdb.exc.BadObject:
            return False
        return True

    def fetch(self, url, refspec):
        repo = git.Repo(self.path)
        try:
            repo.git.fetch(url, refspec)
        except AssertionError:
            repo.git.fetch(url, refspec)

    def deleteRef(self, ref):
        repo = git.Repo(self.path)
        git.Reference.delete(repo, ref)

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
        diff = repo.git.diff('-M', '--color=never', '--numstat', old, new)
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
        #self.log.debug('startold' + repr(old))
        #self.log.debug('startnew' + repr(new))
        for line in self.differ.compare(old, new):
            #self.log.debug('diff output: ' + line)
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
                    #self.log.debug('%s %s %s %s %s' % (i, c, indicator, emphasis, accumulator))
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
                if prevstyle == 'added' or prevstyle == 'context':
                    output_new.append((prevstyle+'-line', prevline))
                if prevstyle == 'removed' or prevstyle == 'context':
                    output_old.append((prevstyle+'-line', prevline))
            if key == '+':
                prevstyle = 'added'
            elif key == '-':
                prevstyle = 'removed'
            elif key == ' ':
                prevstyle = 'context'
            prevline = rest
        #self.log.debug('prev'+repr(prevline))
        if prevline is not None:
            if prevstyle == 'added':
                output_new.append((prevstyle+'-line', prevline))
            elif prevstyle == 'removed':
                output_old.append((prevstyle+'-line', prevline))
        #self.log.debug(repr(output_old))
        #self.log.debug(repr(output_new))
        return output_old, output_new

    header_re = re.compile('@@ -(\d+)(,\d+)? \+(\d+)(,\d+)? @@')
    def diff(self, old, new, context=10000, show_old_commit=False):
        """Create a diff from old to new.

        Note that the commit message is also diffed, and listed as /COMMIT_MSG.
        """
        repo = git.Repo(self.path)
        #'-y', '-x', 'diff -C10', old, new, path).split('\n'):
        oldc = repo.commit(old)
        newc = repo.commit(new)
        files = []
        extra_contexts = []
        if show_old_commit:
            extra_contexts.append(CommitContext(oldc, newc))
        else:
            extra_contexts.append(CommitContext(None, newc))
        contexts = itertools.chain(
            extra_contexts, oldc.diff(
                newc, color='never',create_patch=True, U=context))
        for diff_context in contexts:
            # Each iteration of this is a file
            f = DiffFile()
            if diff_context.a_blob:
                f.oldname = diff_context.a_blob.path
            if diff_context.b_blob:
                f.newname = diff_context.b_blob.path
            # TODO(jeblair): if/when https://github.com/gitpython-developers/GitPython/pull/266 merges,
            # remove above 4 lines and replace with these two:
            # f.oldname = diff_context.a_path
            # f.newname = diff_context.b_path
            if diff_context.new_file:
                f.oldname = 'Empty file'
                f.old_empty = True
            if diff_context.deleted_file:
                f.newname = 'Empty file'
                f.new_empty = True
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
                    continue
                if line.startswith('+++'):
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
                if line.startswith("Binary files"):
                    continue
                if not last_line:
                    raise Exception("Unhandled line: %s" % line)
            if not diff_context.diff:
                # There is no diff, possibly because this is simply a
                # rename.  Include context lines so that comments may
                # appear.
                if not f.new_empty:
                    blob = newc.tree[f.newname]
                else:
                    blob = oldc.tree[f.oldname]
                f.old_lineno = 1
                f.new_lineno = 1
                for line in blob.data_stream.read().splitlines():
                    f.addContextLine(line)
            f.finalize()
        return files

    def getFile(self, old, new, path):
        f = DiffFile()
        f.oldname = path
        f.newname = path
        f.old_lineno = 1
        f.new_lineno = 1
        repo = git.Repo(self.path)
        newc = repo.commit(new)
        try:
            blob = newc.tree[path]
        except KeyError:
            return None
        for line in blob.data_stream.read().splitlines():
            f.addContextLine(line)
        f.finalize()
        return f

def get_repo(project_name, config):
    local_path = os.path.join(config.git_root, project_name)
    local_root = os.path.abspath(config.git_root)
    assert os.path.commonprefix((local_root, local_path)) == local_root
    return Repo(config.url+'p/'+project_name, local_path)
