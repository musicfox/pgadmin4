##########################################################################
#
# pgAdmin 4 - PostgreSQL Tools
#
# Copyright (C) 2013 - 2020, The pgAdmin Development Team
# This software is released under the PostgreSQL Licence
#
##########################################################################

import uuid
import json

from pgadmin.browser.server_groups.servers.databases.schemas.tests import \
    utils as schema_utils
from pgadmin.browser.server_groups.servers.databases.tests import utils as \
    database_utils
from pgadmin.utils.route import BaseTestGenerator
from regression import parent_node_dict
from regression.python_test_utils import test_utils as utils
from pgadmin.browser.server_groups.servers.databases.schemas.tables.tests \
    import utils as tables_utils
from pgadmin.browser.server_groups.servers.databases.schemas.tables.\
    constraints.check_constraint.tests import utils as chk_constraint_utils
from pgadmin.browser.server_groups.servers.databases.schemas.tables.\
    constraints.exclusion_constraint.tests import utils as exclusion_utils
from pgadmin.browser.server_groups.servers.databases.schemas.tables.\
    constraints.foreign_key.tests import utils as fk_utils
from pgadmin.browser.server_groups.servers.databases.schemas.tables.\
    constraints.index_constraint.tests import utils as index_constraint_utils


class ConstraintDeleteMultipleTestCase(BaseTestGenerator):
    """This class will delete constraints under table node."""
    scenarios = [
        # Fetching default URL for table node.
        ('Delete Constraints', dict(url='/browser/constraints/obj/'))
    ]

    def setUp(self):
        self.db_name = parent_node_dict["database"][-1]["db_name"]
        schema_info = parent_node_dict["schema"][-1]
        self.server_id = schema_info["server_id"]
        self.db_id = schema_info["db_id"]
        db_con = database_utils.connect_database(self, utils.SERVER_GROUP,
                                                 self.server_id, self.db_id)
        if not db_con['data']["connected"]:
            raise Exception("Could not connect to database to add a table.")
        self.schema_id = schema_info["schema_id"]
        self.schema_name = schema_info["schema_name"]
        schema_response = schema_utils.verify_schemas(self.server,
                                                      self.db_name,
                                                      self.schema_name)
        if not schema_response:
            raise Exception("Could not find the schema to add a table.")
        self.table_name = "table_constraint_delete_%s" % \
                          (str(uuid.uuid4())[1:8])
        self.table_id = tables_utils.create_table(self.server,
                                                  self.db_name,
                                                  self.schema_name,
                                                  self.table_name)
        # Create Check Constraints
        self.check_constraint_name = "test_constraint_delete_%s" % \
                                     (str(uuid.uuid4())[1:8])
        self.check_constraint_id = \
            chk_constraint_utils.create_check_constraint(
                self.server, self.db_name, self.schema_name, self.table_name,
                self.check_constraint_name)

        self.check_constraint_name_1 = "test_constraint_delete1_%s" % (
            str(uuid.uuid4())[1:8])
        self.check_constraint_id_1 = \
            chk_constraint_utils.create_check_constraint(
                self.server, self.db_name, self.schema_name, self.table_name,
                self.check_constraint_name_1)

        # Create Exclusion Constraint
        self.exclustion_constraint_name = "test_exclusion_get_%s" % (
            str(uuid.uuid4())[1:8])
        self.exclustion_constraint_id = \
            exclusion_utils.create_exclusion_constraint(
                self.server, self.db_name, self.schema_name, self.table_name,
                self.exclustion_constraint_name
            )

        # Create Foreign Key
        self.foreign_table_name = "foreign_table_foreignkey_get_%s" % \
                                  (str(uuid.uuid4())[1:8])
        self.foreign_table_id = tables_utils.create_table(
            self.server, self.db_name, self.schema_name,
            self.foreign_table_name)
        self.foreign_key_name = "test_foreignkey_get_%s" % \
                                (str(uuid.uuid4())[1:8])
        self.foreign_key_id = fk_utils.create_foreignkey(
            self.server, self.db_name, self.schema_name, self.table_name,
            self.foreign_table_name)

        # Create Primary Key
        self.primary_key_name = "test_primary_key_get_%s" % \
                                (str(uuid.uuid4())[1:8])
        self.primary_key_id = \
            index_constraint_utils.create_index_constraint(
                self.server, self.db_name, self.schema_name, self.table_name,
                self.primary_key_name, "PRIMARY KEY")

        # Create Unique Key constraint
        self.unique_constraint_name = "test_unique_constraint_get_%s" % (
            str(uuid.uuid4())[1:8])

        self.unique_constraint_id = \
            index_constraint_utils.create_index_constraint(
                self.server, self.db_name, self.schema_name, self.table_name,
                self.unique_constraint_name, "UNIQUE")

    def runTest(self):
        """This function will delete constraints under table node."""
        data = {'ids': [
            {'id': self.check_constraint_id, '_type': 'check_constraint'},
            {'id': self.check_constraint_id_1, '_type': 'check_constraint'},
            {'id': self.exclustion_constraint_id,
             '_type': 'exclustion_constraint'},
            {'id': self.foreign_key_id, '_type': 'foreign_key'},
            {'id': self.primary_key_id, '_type': 'index_constraint'},
            {'id': self.unique_constraint_id, '_type': 'index_constraint'}
        ]}
        response = self.tester.delete(self.url + str(utils.SERVER_GROUP) +
                                      '/' + str(self.server_id) + '/' +
                                      str(self.db_id) + '/' +
                                      str(self.schema_id) + '/' +
                                      str(self.table_id) + '/',
                                      data=json.dumps(data),
                                      content_type='html/json',
                                      follow_redirects=True)
        self.assertEquals(response.status_code, 200)

    def tearDown(self):
        # Disconnect the database
        database_utils.disconnect_database(self, self.server_id, self.db_id)
