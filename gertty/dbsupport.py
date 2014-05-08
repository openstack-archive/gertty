# Copyright 2014 Mirantis Inc.
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

import copy
import six
import uuid

from alembic import op
import sqlalchemy

def sqlite_drop_columns(table_name, drop_column_names):
    """It implements DROP COLUMN for SQLite.

    The DROP COLUMN command isn't supported by SQLite specification.
    Instead of calling DROP COLUMN it uses the following workaround:

    * create temp table '{table_name}_{rand_uuid}' w/o dropped column;
    * copy all data with remaining columns to the temp table;
    * drop old table;
    * rename temp table to the old table name.
    """

    connection = op.get_bind()
    meta = sqlalchemy.MetaData(bind=connection)
    meta.reflect()

    # construct lists of all needed columns and their names
    column_names = []  # names of remaining columns
    binded_columns = []  # list of columns with table reference
    unbound_columns = []  # list of columns without table reference

    for column in meta.tables[table_name].columns:
        if column.name in drop_column_names:
            continue
        column_names.append(column.name)
        binded_columns.append(column)
        unbound_column = copy.copy(column)
        unbound_column.table = None
        unbound_columns.append(unbound_column)

    # create temp table
    tmp_table_name = "%s_%s" % (table_name, six.text_type(uuid.uuid4()))
    op.create_table(tmp_table_name, *unbound_columns)
    meta.reflect()

    # copy data from the old table to the temp one
    sql_select = sqlalchemy.sql.select(binded_columns)
    connection.execute(sqlalchemy.sql.insert(meta.tables[tmp_table_name])
                       .from_select(column_names, sql_select))

    # drop the old table and rename temp table to the old table name
    op.drop_table(table_name)
    op.rename_table(tmp_table_name, table_name)


def sqlite_alter_columns(table_name, column_defs):
    """Implement alter columns for SQLite.

    The ALTER COLUMN command isn't supported by SQLite specification.
    Instead of calling ALTER COLUMN it uses the following workaround:

    * create temp table '{table_name}_{rand_uuid}', with some column
      defs replaced;
    * copy all data to the temp table;
    * drop old table;
    * rename temp table to the old table name.
    """
    connection = op.get_bind()
    meta = sqlalchemy.MetaData(bind=connection)
    meta.reflect()

    changed_columns = {}
    for col in column_defs:
        changed_columns[col.name] = col

    # construct lists of all columns and their names
    old_columns = []
    new_columns = []
    column_names = []
    for column in meta.tables[table_name].columns:
        column_names.append(column.name)
        old_columns.append(column)
        if column.name in changed_columns.keys():
            new_columns.append(changed_columns[column.name])
        else:
            col_copy = copy.copy(column)
            col_copy.table = None
            new_columns.append(col_copy)

    # create temp table
    tmp_table_name = "%s_%s" % (table_name, six.text_type(uuid.uuid4()))
    op.create_table(tmp_table_name, *new_columns)
    meta.reflect()

    try:
        # copy data from the old table to the temp one
        sql_select = sqlalchemy.sql.select(old_columns)
        connection.execute(sqlalchemy.sql.insert(meta.tables[tmp_table_name])
                           .from_select(column_names, sql_select))
    except Exception:
        op.drop_table(tmp_table_name)
        raise

    # drop the old table and rename temp table to the old table name
    op.drop_table(table_name)
    op.rename_table(tmp_table_name, table_name)
