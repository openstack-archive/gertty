# Copyright 2014 OpenStack Foundation
# Copyright 2014 Hewlett-Packard Development Company, L.P.
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
import sys

import gertty.config
import gertty.version


def set_reqeusts_log_level(level):
    # Python2.6 Logger.setLevel doesn't convert string name
    # to integer code. Here, we set the requests logger level to
    # be less verbose, since our logging output duplicates some
    # requests logging content in places.
    req_level_name = 'WARN'
    req_logger = logging.getLogger('requests')
    if sys.version_info < (2, 7):
        level = logging.getLevelName(req_level_name)
        req_logger.setLevel(level)
    else:
        req_logger.setLevel(req_level_name)


def version():
    return "Gertty version: %s" % gertty.version.version_info.version_string()


def add_common_arguments(parser):
    """Adds the arguments common to all Gertty scripts."""
    parser.add_argument('-c', dest='path',
                        default=gertty.config.DEFAULT_CONFIG_PATH,
                        help='path to config file')
    parser.add_argument('-v', dest='verbose', action='store_true',
                        help='enable more verbose logging')
    parser.add_argument('-d', dest='debug', action='store_true',
                        help='enable debug logging')
    parser.add_argument('--version', dest='version', action='version',
                        version=version(),
                        help='show Gertty\'s version')
    parser.add_argument('server', nargs='?',
                        help='the server to use (as specified in config file)')
