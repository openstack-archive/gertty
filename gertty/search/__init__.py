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

import sqlalchemy.sql.expression
from sqlalchemy.sql.expression import and_

from gertty.search import tokenizer, parser
import gertty.db


class SearchSyntaxError(Exception):
    pass


class SearchCompiler(object):
    def __init__(self, username):
        self.username = username
        self.lexer = tokenizer.SearchTokenizer()
        self.parser = parser.SearchParser()

    def findTables(self, expression):
        tables = set()
        stack = [expression]
        while stack:
            x = stack.pop()
            if hasattr(x, 'table'):
                if (x.table != gertty.db.change_table
                    and hasattr(x.table, 'name')):
                    tables.add(x.table)
            for child in x.get_children():
                if not isinstance(child, sqlalchemy.sql.selectable.Select):
                    stack.append(child)
        return tables

    def parse(self, data):
        self.parser.username = self.username
        result = self.parser.parse(data, lexer=self.lexer)
        tables = self.findTables(result)
        if gertty.db.project_table in tables:
            result = and_(gertty.db.change_table.c.project_key == gertty.db.project_table.c.key,
                          result)
            tables.remove(gertty.db.project_table)
        if gertty.db.account_table in tables:
            result = and_(gertty.db.change_table.c.account_key == gertty.db.account_table.c.key,
                          result)
            tables.remove(gertty.db.account_table)
        if gertty.db.file_table in tables:
            result = and_(gertty.db.file_table.c.revision_key == gertty.db.revision_table.c.key,
                          gertty.db.revision_table.c.change_key == gertty.db.change_table.c.key,
                          result)
            tables.remove(gertty.db.file_table)
        if tables:
            raise Exception("Unknown table in search: %s" % tables)
        return result

if __name__ == '__main__':
    class Dummy(object):
        pass
    query = 'status:open limit:50 age:2months'
    lexer = tokenizer.SearchTokenizer()
    lexer.input(query)
    while True:
        token = lexer.token()
        if not token:
            break
        print token

    app = Dummy()
    app.config = Dummy()
    app.config.username = 'bob'
    search = SearchCompiler(app.config.username)
    x = search.parse(query)
    print x
