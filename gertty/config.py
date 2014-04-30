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
import ConfigParser


DEFAULT_CONFIG_PATH='~/.gerttyrc'

class Config(object):
    def __init__(self, server=None, path=DEFAULT_CONFIG_PATH):
        self.path = os.path.expanduser(path)
        self.config = ConfigParser.RawConfigParser()
        with open(self.path, 'r') as f:
            self.config.readfp(f, filename=f.name)
        if server is None:
            server = self.config.sections()[0]
        self.server = server
        self.url = self.config.get(server, 'url')
        self.username = self.config.get(server, 'username')
        if not self.config.has_option(server, 'password'):
            password = getpass.getpass("Password for %s (%s): "
                                       % (self.url, self.username))
        else:
            self.password = self.config.get(server, 'password')
        if self.config.has_option(server, 'verify_ssl'):
            self.verify_ssl = self.config.getboolean(server, 'verify_ssl')
        else:
            self.verify_ssl = True
        if not self.verify_ssl:
            os.environ['GIT_SSL_NO_VERIFY']='true'
        self.git_root = os.path.expanduser(self.config.get(server, 'git_root'))
        if self.config.has_option(server, 'dburi'):
            self.dburi = self.config.get(server, 'dburi')
        else:
            self.dburi = 'sqlite:///' + os.path.expanduser('~/.gertty.db')
        if self.config.has_option(server, 'log_file'):
            self.log_file = os.path.expanduser(self.config.get(server, 'log_file'))
        else:
            self.log_file = os.path.expanduser('~/.gertty.log')
