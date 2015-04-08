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

import argparse
import collections
import logging
import os
import sys

import prettytable

import gertty.app
import gertty.config
import gertty.db
import gertty.gitrepo
import gertty.search
import gertty.version


WELCOME_TEXT = """\
Welcome to Gertty's CLI!

To get started, you should subscribe to some projects.  This means
that you must actually run 'gertty' to get stated.  Once you are all
configured then the CLI will be functional.

"""


class App(object):
    def __init__(self, server=None, debug=False, verbose=False,
                 path=gertty.config.DEFAULT_CONFIG_PATH):
        self.server = server
        self.config = gertty.config.Config(server=server, path=path)
        if debug:
            level = logging.DEBUG
        elif verbose:
            level = logging.INFO
        else:
            level = logging.WARNING

        if debug:
            logging.basicConfig(format='%(asctime)s %(message)s',
                                level=level)
        else:
            logging.basicConfig(filename=self.config.log_file, filemode='w',
                                format='%(asctime)s %(message)s',
                                level=level)

        gertty.app.set_reqeusts_log_level(level)

        self.log = logging.getLogger('gertty.cli')
        self.log.debug("Starting")

        search = gertty.search.SearchCompiler(self.config.username)
        self.db = gertty.db.Database(self.config.dburi, search)

        has_subscribed_projects = False
        with self.db.getSession() as session:
            if session.getProjects(subscribed=True):
                has_subscribed_projects = True
        if not has_subscribed_projects:
            self.welcome()

        self.gertty = GerttyFacade(self.config, self.db)

    def welcome(self):
        print(WELCOME_TEXT)

    def list_projects(self):
        print('Listing subscribed projects')
        cols = ['name', 'description', 'updated']
        table = prettytable.PrettyTable([c.title() for c in cols])
        table.align['Name'] = 'l'
        for project in self.gertty.projects():
            table.add_row([project[col] for col in cols])
        print(table)

    def list_reviews(self, project_name):
        print('Listing reviews for', project_name)
        cols = ['change_id', 'status', 'updated', 'subject']
        table = prettytable.PrettyTable([c.title() for c in cols])
        table.align['Subject'] = 'l'
        for review in self.gertty.reviews(project_name):
            table.add_row([review[col] for col in cols])
        print(table)

    def checkout(self, changeset_id, patchset=None):
        self.gertty.checkout(changeset_id, patchset)


def get_repo(config, project_name):
    """Ripped from App.getRepo."""
    local_path = os.path.join(config.git_root, project_name)
    local_root = os.path.abspath(config.git_root)
    assert os.path.commonprefix((local_root, local_path)) == local_root
    return gertty.gitrepo.Repo(config.url + 'p/' + project_name,
                               local_path)

def version():
    return "Gertty version: %s" % gertty.version.version_info.version_string()


def main():
    parser = argparse.ArgumentParser(description='gertty CLI')
    gertty.app.add_common_arguments(parser)

    subparsers = parser.add_subparsers(title='commands')

    projects = subparsers.add_parser('projects',
                                     help='show a list of projects')
    projects.set_defaults(cmd='projects')

    reviews = subparsers.add_parser('reviews', help='show a list of reviews')
    reviews.add_argument('project_name', help='project name')
    reviews.set_defaults(cmd='reviews')

    checkout = subparsers.add_parser('checkout', help='checkout a patchset')
    checkout.add_argument('changeset_id', help='changeset_id')
    checkout.add_argument('--patchset', default=None, help='patchset')
    checkout.set_defaults(cmd='checkout')

    args = parser.parse_args()
    app = App(server=args.server, debug=args.debug, verbose=args.verbose,
              path=args.path)
    if args.cmd == 'projects':
        app.list_projects()
    elif args.cmd == 'reviews':
        app.list_reviews(args.project_name)
    elif args.cmd == 'checkout':
        app.checkout(args.changeset_id, args.patchset)
    return 0


class GerttyFacade(object):

    def __init__(self, config, db):
        self.config = config
        self.db = db

    def _session(self):
        return self.db.getSession()

    def projects(self, subscribed=True, unreviewed=True):
        session = self._session()
        projects = session.getProjects(subscribed=subscribed,
                                       unreviewed=unreviewed)
        for project in projects:
            yield {'name': project.name,
                   'description': project.description,
                   'updated': project.updated}

    def reviews(self, project_name):
        project = self._session().getProjectByName(project_name)
        query = ('_project_key:%d %s' %
                 (project.key, self.config.project_change_list_query))
        session = self._session()
        for change in self._session().getChanges(query, sort_by='updated'):
            yield {
                'change_id': change.change_id,
                'status': change.status,
                'updated': change.updated,
                'subject': change.subject,
            }

    def checkout(self, changeset_id, patchset=-1):
        patchset = patchset or -1
        change = self._session().getChangeByChangeID(changeset_id)
        revision = list(change.revisions)[-1]  # TODO: latest for now
        try:
            repo = get_repo(self.config, revision.change.project.name)
            repo.checkout(revision.commit)
            #print 'Change checked out in %s' % repo.path
        except gertty.gitrepo.GitCheckoutError as e:
            print 'ERROR:', e.msg  # TODO: make less stupid

    def comments(self, change_id, revision=-1):
        change = self._session().getChangeByChangeID(change_id)
        revision = list(change.revisions)[revision]
        for comment  in revision.comments:
            yield {
                'author': comment.author.name,
                'draft': comment.draft,
                'created': comment.created,
                'message': comment.message,
                'file': comment.file,
                'line': comment.line,
            }
