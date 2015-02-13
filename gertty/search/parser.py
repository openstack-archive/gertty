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

import datetime
import re

import ply.yacc as yacc
from sqlalchemy.sql.expression import and_, or_, not_, exists, select

import gertty.db
import gertty.search

from tokenizer import tokens

def SearchParser():
    precedence = (
        ('left', 'NOT', 'NEG'),
    )

    def p_terms(p):
        '''expression : list_expr
                      | paren_expr
                      | boolean_expr
                      | negative_expr
                      | term'''
        p[0] = p[1]

    def p_list_expr(p):
        '''list_expr : expression expression'''
        p[0] = and_(p[1], p[2])

    def p_paren_expr(p):
        '''paren_expr : LPAREN expression RPAREN'''
        p[0] = p[2]

    def p_boolean_expr(p):
        '''boolean_expr : expression AND expression
                        | expression OR expression'''
        if p[2] == 'and':
            p[0] = and_(p[1], p[3])
        elif p[2] == 'or':
            p[0] = or_(p[1], p[3])
        else:
            raise SyntaxError()

    def p_negative_expr(p):
        '''negative_expr : NOT expression
                         | NEG expression'''
        p[0] = not_(p[2])

    def p_term(p):
        '''term : age_term
                | change_term
                | owner_term
                | reviewer_term
                | commit_term
                | project_term
                | project_key_term
                | branch_term
                | topic_term
                | ref_term
                | label_term
                | message_term
                | comment_term
                | has_term
                | is_term
                | status_term
                | op_term'''
        p[0] = p[1]

    def p_string(p):
        '''string : SSTRING
                  | DSTRING
                  | USTRING'''
        p[0] = p[1]

    def p_age_unit(p):
        '''age_unit : SECONDS
                    | MINUTES
                    | HOURS
                    | DAYS
                    | WEEKS
                    | MONTHS
                    | YEARS'''
        p[0] = p[1]

    def p_age_term(p):
        '''age_term : OP_AGE NUMBER age_unit'''
        now = datetime.datetime.utcnow()
        delta = p[1]
        unit = p[2]
        if unit == 'minutes':
            delta = delta * 60
        elif unit == 'hours':
            delta = delta * 60 * 60
        elif unit == 'days':
            delta = delta * 60 * 60 * 60
        elif unit == 'weeks':
            delta = delta * 60 * 60 * 60 * 7
        elif unit == 'months':
            delta = delta * 60 * 60 * 60 * 30
        elif unit == 'years':
            delta = delta * 60 * 60 * 60 * 365
        p[0] = gertty.db.change_table.c.updated < (now-delta)

    def p_change_term(p):
        '''change_term : OP_CHANGE CHANGE_ID
                       | OP_CHANGE NUMBER'''
        if type(p[2]) == int:
            p[0] = gertty.db.change_table.c.number == p[2]
        else:
            p[0] = gertty.db.change_table.c.change_id == p[2]

    def p_owner_term(p):
        '''owner_term : OP_OWNER string'''
        if p[2] == 'self':
            username = p.parser.username
            p[0] = gertty.db.account_table.c.username == username
        else:
            p[0] = or_(gertty.db.account_table.c.username == p[2],
                       gertty.db.account_table.c.email == p[2],
                       gertty.db.account_table.c.name == p[2])

    def p_reviewer_term(p):
        '''reviewer_term : OP_REVIEWER string'''
        filters = []
        filters.append(gertty.db.approval_table.c.change_key == gertty.db.change_table.c.key)
        filters.append(gertty.db.approval_table.c.account_key == gertty.db.account_table.c.key)
        if p[2] == 'self':
            username = p.parser.username
            filters.append(gertty.db.account_table.c.username == username)
        else:
            filters.append(or_(gertty.db.account_table.c.username == p[2],
                               gertty.db.account_table.c.email == p[2],
                               gertty.db.account_table.c.name == p[2]))
        s = select([gertty.db.change_table.c.key], correlate=False).where(and_(*filters))
        p[0] = gertty.db.change_table.c.key.in_(s)

    def p_commit_term(p):
        '''commit_term : OP_COMMIT string'''
        filters = []
        filters.append(gertty.db.revision_table.c.change_key == gertty.db.change_table.c.key)
        filters.append(gertty.db.revision_table.c.commit == p[2])
        s = select([gertty.db.change_table.c.key], correlate=False).where(and_(*filters))
        p[0] = gertty.db.change_table.c.key.in_(s)

    def p_project_term(p):
        '''project_term : OP_PROJECT string'''
        #TODO: support regex
        p[0] = gertty.db.project_table.c.name == p[2]

    def p_project_key_term(p):
        '''project_key_term : OP_PROJECT_KEY NUMBER'''
        p[0] = gertty.db.change_table.c.project_key == p[2]

    def p_branch_term(p):
        '''branch_term : OP_BRANCH string'''
        #TODO: support regex
        p[0] = gertty.db.change_table.c.branch == p[2]

    def p_topic_term(p):
        '''topic_term : OP_TOPIC string'''
        #TODO: support regex
        p[0] = gertty.db.change_table.c.topic == p[2]

    def p_ref_term(p):
        '''ref_term : OP_REF string'''
        #TODO: support regex
        p[0] = gertty.db.change_table.c.branch == p[2][len('refs/heads/'):]

    label_re = re.compile(r'(?P<label>[a-zA-Z0-9_-]+([a-zA-Z]|((?<![-+])[0-9])))'
                          r'(?P<operator>[<>]?=?)(?P<value>[-+]?[0-9]+)'
                          r'($|,(user=)?(?P<user>\S+))')

    def p_label_term(p):
        '''label_term : OP_LABEL string'''
        args = label_re.match(p[2])
        label = args.group('label')
        op = args.group('operator') or '='
        value = int(args.group('value'))
        user = args.group('user')

        filters = []
        filters.append(gertty.db.approval_table.c.change_key == gertty.db.change_table.c.key)
        filters.append(gertty.db.approval_table.c.category == label)
        if op == '=':
            filters.append(gertty.db.approval_table.c.value == value)
        elif op == '>=':
            filters.append(gertty.db.approval_table.c.value >= value)
        elif op == '<=':
            filters.append(gertty.db.approval_table.c.value <= value)
        if user is not None:
            filters.append(gertty.db.approval_table.c.account_key == gertty.db.account_table.c.key)
            if user == 'self':
                filters.append(gertty.db.account_table.c.username == p.parser.username)
            else:
                filters.append(
                    or_(gertty.db.account_table.c.username == user,
                        gertty.db.account_table.c.email == user,
                        gertty.db.account_table.c.name == user))
        s = select([gertty.db.change_table.c.key], correlate=False).where(and_(*filters))
        p[0] = gertty.db.change_table.c.key.in_(s)

    def p_message_term(p):
        '''message_term : OP_MESSAGE string'''
        filters = []
        filters.append(gertty.db.revision_table.c.change_key == gertty.db.change_table.c.key)
        filters.append(gertty.db.revision_table.c.message == p[2])
        s = select([gertty.db.change_table.c.key], correlate=False).where(and_(*filters))
        p[0] = gertty.db.change_table.c.key.in_(s)

    def p_comment_term(p):
        '''comment_term : OP_COMMENT string'''
        filters = []
        filters.append(gertty.db.revision_table.c.change_key == gertty.db.change_table.c.key)
        filters.append(gertty.db.revision_table.c.message == p[2])
        revision_select = select([gertty.db.change_table.c.key], correlate=False).where(and_(*filters))
        filters = []
        filters.append(gertty.db.revision_table.c.change_key == gertty.db.change_table.c.key)
        filters.append(gertty.db.comment_table.c.revision_key == gertty.db.revision_table.c.key)
        filters.append(gertty.db.comment_table.c.message == p[2])
        comment_select = select([gertty.db.change_table.c.key], correlate=False).where(and_(*filters))
        p[0] = or_(gertty.db.change_table.c.key.in_(comment_select),
                   gertty.db.change_table.c.key.in_(revision_select))

    def p_has_term(p):
        '''has_term : OP_HAS string'''
        #TODO: implement star
        if p[2] == 'draft':
            filters = []
            filters.append(gertty.db.revision_table.c.change_key == gertty.db.change_table.c.key)
            filters.append(gertty.db.message_table.c.revision_key == gertty.db.revision_table.c.key)
            filters.append(gertty.db.message_table.c.draft == True)
            s = select([gertty.db.change_table.c.key], correlate=False).where(and_(*filters))
            p[0] = gertty.db.change_table.c.key.in_(s)
        else:
            raise gertty.search.SearchSyntaxError('Syntax error: has:%s is not supported' % p[2])

    def p_is_term(p):
        '''is_term : OP_IS string'''
        #TODO: implement watched, draft
        username = p.parser.username
        if p[2] == 'reviewed':
            filters = []
            filters.append(gertty.db.approval_table.c.change_key == gertty.db.change_table.c.key)
            filters.append(gertty.db.approval_table.c.value != 0)
            s = select([gertty.db.change_table.c.key], correlate=False).where(and_(*filters))
            p[0] = gertty.db.change_table.c.key.in_(s)
        elif p[2] == 'open':
            p[0] = gertty.db.change_table.c.status.notin_(['MERGED', 'ABANDONED'])
        elif p[2] == 'closed':
            p[0] = gertty.db.change_table.c.status.in_(['MERGED', 'ABANDONED'])
        elif p[2] == 'submitted':
            p[0] = gertty.db.change_table.c.status == 'SUBMITTED'
        elif p[2] == 'merged':
            p[0] = gertty.db.change_table.c.status == 'MERGED'
        elif p[2] == 'abandoned':
            p[0] = gertty.db.change_table.c.status == 'ABANDONED'
        elif p[2] == 'owner':
            p[0] = gertty.db.account_table.c.username == username
        elif p[2] == 'starred':
            p[0] = gertty.db.change_table.c.starred == True
        elif p[2] == 'reviewer':
            filters = []
            filters.append(gertty.db.approval_table.c.change_key == gertty.db.change_table.c.key)
            filters.append(gertty.db.approval_table.c.account_key == gertty.db.account_table.c.key)
            filters.append(gertty.db.account_table.c.username == username)
            s = select([gertty.db.change_table.c.key], correlate=False).where(and_(*filters))
            p[0] = gertty.db.change_table.c.key.in_(s)
        else:
            raise gertty.search.SearchSyntaxError('Syntax error: is:%s is not supported' % p[2])

    def p_status_term(p):
        '''status_term : OP_STATUS string'''
        if p[2] == 'open':
            p[0] = gertty.db.change_table.c.status.notin_(['MERGED', 'ABANDONED'])
        elif p[2] == 'closed':
            p[0] = gertty.db.change_table.c.status.in_(['MERGED', 'ABANDONED'])
        else:
            p[0] = gertty.db.change_table.c.status == p[2].upper()

    def p_op_term(p):
        'op_term : OP'
        raise SyntaxError()

    def p_error(p):
        if p:
            raise gertty.search.SearchSyntaxError('Syntax error at "%s" in search string "%s" (col %s)' % (
                    p.lexer.lexdata[p.lexpos:], p.lexer.lexdata, p.lexpos))
        else:
            raise gertty.search.SearchSyntaxError('Syntax error: EOF in search string')

    return yacc.yacc(debug=0, write_tables=0)
