#!/bin/sh

exec env PYTHONPATH=. python2 "$(dirname "$0")"/gertty/app.py "$@"
