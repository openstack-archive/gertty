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

import six
import uuid

from alembic import op
import sqlalchemy


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
    indexes = []
    for col in column_defs:
        # If we are to have an index on the column, don't create it
        # immediately, instead, add it to a list of indexes to create
        # after the table rename.
        if col.index:
            indexes.append(('ix_%s_%s' % (table_name, col.name),
                            table_name,
                            [col.name],
                            col.unique))
            col.unique = False
            col.index = False
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
            col_copy = column.copy()
            new_columns.append(col_copy)

    for key in meta.tables[table_name].foreign_keys:
        constraint = key.constraint
        con_copy = constraint.copy()
        new_columns.append(con_copy)

    for index in meta.tables[table_name].indexes:
        # If this is a single column index for a changed column, don't
        # copy it because we may already be creating a new version of
        # it (or removing it).
        idx_columns = [col.name for col in index.columns]
        if len(idx_columns)==1 and idx_columns[0] in changed_columns.keys():
            continue
        # Otherwise, recreate the index.
        indexes.append((index.name,
                        table_name,
                        [col.name for col in index.columns],
                        index.unique))

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

    # (re-)create indexes
    for index in indexes:
        op.create_index(op.f(index[0]), index[1], index[2], unique=index[3])

def sqlite_drop_columns(table_name, drop_columns):
    """Implement drop columns for SQLite.

    The DROP COLUMN command isn't supported by SQLite specification.
    Instead of calling DROP COLUMN it uses the following workaround:

    * create temp table '{table_name}_{rand_uuid}', without
      dropped columns;
    * copy all data to the temp table;
    * drop old table;
    * rename temp table to the old table name.
    """
    connection = op.get_bind()
    meta = sqlalchemy.MetaData(bind=connection)
    meta.reflect()

    # construct lists of all columns and their names
    old_columns = []
    new_columns = []
    column_names = []
    indexes = []
    for column in meta.tables[table_name].columns:
        if column.name not in drop_columns:
            old_columns.append(column)
            column_names.append(column.name)
            col_copy = column.copy()
            new_columns.append(col_copy)

    for key in meta.tables[table_name].foreign_keys:
        # If this is a single column constraint for a dropped column,
        # don't copy it.
        if isinstance(key.constraint.columns, sqlalchemy.sql.base.ColumnCollection):
            # This is needed for SQLAlchemy >= 1.0.4
            columns = [c.name for c in key.constraint.columns]
        else:
            # This is needed for SQLAlchemy <= 0.9.9.  This is
            # backwards compat code just in case someone updates
            # Gertty without updating SQLAlchemy.  This is simple
            # enough to check and will hopefully avoid leaving the
            # user's db in an inconsistent state.  Remove this after
            # Gertty 1.2.0.
            columns = key.constraint.columns
        if (len(columns)==1 and columns[0] in drop_columns):
            continue
        # Otherwise, recreate the constraint.
        constraint = key.constraint
        con_copy = constraint.copy()
        new_columns.append(con_copy)

    for index in meta.tables[table_name].indexes:
        # If this is a single column index for a dropped column, don't
        # copy it.
        idx_columns = [col.name for col in index.columns]
        if len(idx_columns)==1 and idx_columns[0] in drop_columns:
            continue
        # Otherwise, recreate the index.
        indexes.append((index.name,
                        table_name,
                        [col.name for col in index.columns],
                        index.unique))

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

    # (re-)create indexes
    for index in indexes:
        op.create_index(op.f(index[0]), index[1], index[2], unique=index[3])
