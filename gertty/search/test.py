import gertty.search
import re
import sys

label_re = re.compile(r'(?P<label>[a-zA-Z0-9_-]+([a-zA-Z]|((?<![-+])[0-9])))'
                      r'(?P<operator>[<>]?=?)(?P<value>[-+]?[0-9]+)'
                      r'($|,user=(?P<user>\S+))')

for a in [
    'Code-Review=1',
    'Code-Review=+1',
    'Code-Review=-1',
    'Code-Review>=+1',
    'Code-Review<=-1',
    'Code-Review+1',
    'Code-Review-1',
    ]:
    for b in [
        '',
        ',user=corvus',
        ]:
        data = a+b
        print
        print data
        m = label_re.match(data)
        print 'res', m and m.groups()

#sys.exit(0)
parser = gertty.search.SearchCompiler(None)

import tokenizer
lexer = tokenizer.SearchTokenizer()
lexer.input("project:foo/bar")

# Tokenize
while True:
    tok = lexer.token()
    if not tok: break      # No more input
    print tok

#TODO: unit test
for a in [
    'label:Code-Review=1',
    'label:Code-Review=+1',
    'label:Code-Review=-1',
    'label:Code-Review>=+1',
    'label:Code-Review<=-1',
    'label:Code-Review+1',
    'label:Code-Review-1',
    ]:
    for b in [
        '',
        ',user=corvus',
        ]:
        data = a+b
        print
        print data
        result = parser.parse(data)
        print 'res', str(result)

for data in [
    '_project_key:18 status:open',
    'project:foo/bar status:open',
    'project:foo and status:open',
    'project:foo or status:open',
    'project:foo and (status:merged or status:new)',
    'project:foo or project:bar or project:baz',
    'project:foo project:bar project:baz',
    ]:
    print
    print data
    result = parser.parse(data)
    print 'res', str(result)
