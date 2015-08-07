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
    'file': 'OP_FILE',
    'has': 'OP_HAS',
    'is': 'OP_IS',
    'status': 'OP_STATUS',
    'limit': 'OP_LIMIT',
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
    'NUMBER',
    'CHANGE_ID',
    'SSTRING',
    'DSTRING',
    'USTRING',
    #'REGEX',
    #'SHA',
    ] + operators.values()

def SearchTokenizer():
    t_LPAREN = r'\('   # NOQA
    t_RPAREN = r'\)'   # NOQA
    t_NEG    = r'[-!]' # NOQA
    t_ignore = ' \t'   # NOQA (and intentionally not using r'' due to tab char)

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
        r'([^\s\(\)!-][^\s\(\)!]*)'
        t.value=t.value.decode("string-escape")
        return t

    def t_newline(t):
        r'\n+'
        t.lexer.lineno += len(t.value)

    def t_error(t):
        print "Illegal character '%s'" % t.value[0]
        t.lexer.skip(1)

    return lex.lex()
