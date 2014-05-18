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

import getpass
import os
import yaml

import voluptuous as v

import gertty.commentlink
import gertty.palette

DEFAULT_CONFIG_PATH='~/.gertty.yaml'

class ConfigSchema(object):
    server = {v.Required('name'): str,
              v.Required('url'): str,
              v.Required('username'): str,
              'password': str,
              'verify_ssl': bool,
              'dburi': str,
              v.Required('git_root'): str,
              'log_file': str,
              }

    servers = [server]

    text_replacement = {'text': v.Any(str,
                                      {'color': str,
                                       v.Required('text'): str})}

    replacement = v.Any(text_replacement)

    palette = {v.Required('name'): str,
               v.Match('(?!name)'): [str]}

    palettes = [palette]

    commentlink = {v.Required('match'): str,
                   v.Required('replacements'): [replacement]}

    commentlinks = [commentlink]

    def getSchema(self, data):
        schema = v.Schema({v.Required('servers'): self.servers,
                           'palettes': self.palettes,
                           'commentlinks': self.commentlinks,
                           })
        return schema

class Config(object):
    def __init__(self, server=None, palette='default',
                 path=DEFAULT_CONFIG_PATH):
        self.path = os.path.expanduser(path)

        if not os.path.exists(self.path):
            self.printSample()
            exit(1)

        self.config = yaml.load(open(self.path))
        schema = ConfigSchema().getSchema(self.config)
        schema(self.config)
        server = self.getServer(server)
        self.server = server
        url = server['url']
        if not url.endswith('/'):
            url += '/'
        self.url = url
        self.username = server['username']
        self.password = server.get('password')
        if self.password is None:
            self.password = getpass.getpass("Password for %s (%s): "
                                            % (self.url, self.username))
        self.verify_ssl = server.get('verify_ssl', True)
        if not self.verify_ssl:
            os.environ['GIT_SSL_NO_VERIFY']='true'
        self.git_root = os.path.expanduser(server['git_root'])
        self.dburi = server.get('dburi',
                                'sqlite:///' + os.path.expanduser('~/.gertty.db'))
        log_file = server.get('log_file', '~/.gertty.log')
        self.log_file = os.path.expanduser(log_file)

        self.palettes = {}
        for p in self.config.get('palettes', []):
            self.palettes[p['name']] = gertty.palette.Palette(p)
        if not self.palettes:
            self.palettes['default'] = gertty.palette.Palette({})
        self.palette = self.palettes[palette]

        self.commentlinks = [gertty.commentlink.CommentLink(c)
                             for c in self.config.get('commentlinks', [])]

    def getServer(self, name=None):
        for server in self.config['servers']:
            if name is None or name == server['name']:
                return server
        return None

    def printSample(self):
        print """Please create a configuration file ~/.gertty.yaml

Example:

-----8<-------8<-----8<-----8<---
servers:
  - name: gerrit
    url: https://review.example.org/
    username: <gerrit username>
    password: <gerrit password>
    git_root: ~/git/
-----8<-------8<-----8<-----8<---

Then invoke:
  gertty gerrit
        """
