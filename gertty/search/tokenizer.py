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

import ply.lex as lex

operators = {
    'age': 'OP_AGE',
    'change': 'OP_CHANGE',
    'owner': 'OP_OWNER',
    #'OP_OWNERIN', # needs local group membership
    'reviewer': 'OP_REVIEWER',
    #'OP_REVIEWERIN', # needs local group membership
    'commit': 'OP_COMMIT',
    'project': 'OP_PROJECT',
    '_project_key': 'OP_PROJECT_KEY',  # internal gertty use only
    'branch': 'OP_BRANCH',
    'topic': 'OP_TOPIC',
    'ref': 'OP_REF',
    #'tr': 'OP_TR', # needs trackingids
    #'bug': 'OP_BUG', # needs trackingids
    'label': 'OP_LABEL',
    'message': 'OP_MESSAGE',
    'comment': 'OP_COMMENT',
    #'file': 'OP_FILE', # needs local file list
    'has': 'OP_HAS',
    'is': 'OP_IS',
    'status': 'OP_STATUS',
    }

reserved = {
    'or|OR': 'OR',
    'not|NOT': 'NOT',
    }

tokens = [
    'OP',
    'AND',
    'OR',
    'NOT',
    'NEG',
    'LPAREN',
    'RPAREN',
    'SECONDS',
    'MINUTES',
    'HOURS',
    'DAYS',
    'WEEKS',
    'MONTHS',
    'YEARS',
    'NUMBER',
    'CHANGE_ID',
    'SSTRING',
    'DSTRING',
    'USTRING',
    #'REGEX',
    #'SHA',
    ] + operators.values()

def SearchTokenizer():
    t_LPAREN     = r'\('
    t_RPAREN     = r'\)'
    t_NEG        = r'!'

    def t_OP(t):
        r'[a-zA-Z_][a-zA-Z_]*:'
        t.type = operators.get(t.value[:-1], 'OP')
        return t

    def t_CHANGE_ID(t):
        r'I[a-fA-F0-9]{7,40}'
        return t

    def t_SSTRING(t):
        r"'([^\\']+|\\'|\\\\)*'"
        t.value=t.value[1:-1].decode("string-escape")
        return t

    def t_DSTRING(t):
        r'"([^\\"]+|\\"|\\\\)*"'
        t.value=t.value[1:-1].decode("string-escape")
        return t

    def t_AND(t):
        r'and|AND'
        return t

    def t_OR(t):
        r'or|OR'
        return t

    def t_NOT(t):
        r'not|NOT'
        return t

    def t_INTEGER(t):
        r'[+-]\d+'
        t.value = int(t.value)
        return t

    def t_NUMBER(t):
        r'\d+'
        t.value = int(t.value)
        return t

    def t_USTRING(t):
        r'([^\s\(\)!]+)'
        t.value=t.value.decode("string-escape")
        return t

    def t_SECONDS(t):
        r's|sec|second|seconds'
        t.value = 'seconds'

    def t_MINUTES(t):
        r'm|min|minute|minutes'
        t.value = 'minutes'

    def t_HOURS(t):
        r'h|hr|hour|hours'
        t.value = 'hours'

    def t_DAYS(t):
        r'd|day|days'
        t.value = 'days'

    def t_WEEKS(t):
        r'w|week|weeks'
        t.value = 'weeks'

    def t_MONTHS(t):
        r'mon|month|months'
        t.value = 'months'

    def t_YEARS(t):
        r'y|year|years'
        t.value = 'years'

    def t_newline(t):
        r'\n+'
        t.lexer.lineno += len(t.value)

    t_ignore  = ' \t'

    def t_error(t):
        print "Illegal character '%s'" % t.value[0]
        t.lexer.skip(1)

    return lex.lex()
