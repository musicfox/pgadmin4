##########################################################################
#
# pgAdmin 4 - PostgreSQL Tools
#
# Copyright (C) 2013 - 2020, The pgAdmin Development Team
# This software is released under the PostgreSQL Licence
#
##########################################################################

"""Implements the Database Node"""

import re
from functools import wraps

import simplejson as json
from flask import render_template, current_app, request, jsonify
from flask_babelex import gettext as _
from flask_security import current_user

import pgadmin.browser.server_groups.servers as servers
from config import PG_DEFAULT_DRIVER
from pgadmin.browser.collection import CollectionNodeModule
from pgadmin.browser.server_groups.servers.databases.utils import \
    parse_sec_labels_from_db, parse_variables_from_db
from pgadmin.browser.server_groups.servers.utils import parse_priv_from_db, \
    parse_priv_to_db
from pgadmin.browser.utils import PGChildNodeView
from pgadmin.utils.ajax import gone
from pgadmin.utils.ajax import make_json_response, \
    make_response as ajax_response, internal_server_error, unauthorized
from pgadmin.utils.driver import get_driver
from pgadmin.tools.sqleditor.utils.query_history import QueryHistory

from pgadmin.tools.schema_diff.node_registry import SchemaDiffRegistry
from pgadmin.model import Server


class DatabaseModule(CollectionNodeModule):
    NODE_TYPE = 'database'
    COLLECTION_LABEL = _("Databases")

    def __init__(self, *args, **kwargs):
        self.min_ver = None
        self.max_ver = None

        super(DatabaseModule, self).__init__(*args, **kwargs)

    def get_nodes(self, gid, sid):
        """
        Generate the collection node
        """
        if self.show_node:
            yield self.generate_browser_collection_node(sid)

    @property
    def script_load(self):
        """
        Load the module script for server, when any of the server-group node is
        initialized.
        """
        return servers.ServerModule.NODE_TYPE

    @property
    def csssnippets(self):
        """
        Returns a snippet of css to include in the page
        """
        snippets = [
            render_template(
                "browser/css/collection.css",
                node_type=self.node_type,
                _=_
            ),
            render_template(
                "databases/css/database.css",
                node_type=self.node_type,
                _=_
            )
        ]

        for submodule in self.submodules:
            snippets.extend(submodule.csssnippets)

        return snippets

    @property
    def module_use_template_javascript(self):
        """
        Returns whether Jinja2 template is used for generating the javascript
        module.
        """
        return False


blueprint = DatabaseModule(__name__)


class DatabaseView(PGChildNodeView):
    node_type = blueprint.node_type

    parent_ids = [
        {'type': 'int', 'id': 'gid'},
        {'type': 'int', 'id': 'sid'}
    ]
    ids = [
        {'type': 'int', 'id': 'did'}
    ]

    operations = dict({
        'obj': [
            {'get': 'properties', 'delete': 'delete', 'put': 'update'},
            {'get': 'list', 'post': 'create', 'delete': 'delete'}
        ],
        'nodes': [
            {'get': 'node'},
            {'get': 'nodes'}
        ],
        'get_databases': [
            {'get': 'get_databases'},
            {'get': 'get_databases'}
        ],
        'sql': [
            {'get': 'sql'}
        ],
        'msql': [
            {'get': 'msql'},
            {'get': 'msql'}
        ],
        'stats': [
            {'get': 'statistics'},
            {'get': 'statistics'}
        ],
        'dependency': [
            {'get': 'dependencies'}
        ],
        'dependent': [
            {'get': 'dependents'}
        ],
        'children': [
            {'get': 'children'}
        ],
        'connect': [
            {
                'get': 'connect_status',
                'post': 'connect',
                'delete': 'disconnect'
            }
        ],
        'get_encodings': [
            {'get': 'get_encodings'},
            {'get': 'get_encodings'}
        ],
        'get_ctypes': [
            {'get': 'get_ctypes'},
            {'get': 'get_ctypes'}
        ],
        'vopts': [
            {}, {'get': 'variable_options'}
        ]
    })

    def check_precondition(action=None):
        """
        This function will behave as a decorator which will checks
        database connection before running view, it will also attaches
        manager,conn & template_path properties to self
        """

        def wrap(f):
            @wraps(f)
            def wrapped(self, *args, **kwargs):
                self.manager = get_driver(
                    PG_DEFAULT_DRIVER
                ).connection_manager(
                    kwargs['sid']
                )
                if self.manager is None:
                    return gone(errormsg=_("Could not find the server."))

                self.datlastsysoid = 0
                if action and action in ["drop"]:
                    self.conn = self.manager.connection()
                elif 'did' in kwargs:
                    self.conn = self.manager.connection(did=kwargs['did'])
                    self.db_allow_connection = True
                    # If connection to database is not allowed then
                    # provide generic connection
                    if kwargs['did'] in self.manager.db_info:
                        self._db = self.manager.db_info[kwargs['did']]
                        self.datlastsysoid = self._db['datlastsysoid']
                        if self._db['datallowconn'] is False:
                            self.conn = self.manager.connection()
                            self.db_allow_connection = False
                else:
                    self.conn = self.manager.connection()

                # set template path for sql scripts
                self.template_path = 'databases/sql/#{0}#'.format(
                    self.manager.version
                )

                return f(self, *args, **kwargs)

            return wrapped

        return wrap

    @check_precondition(action="list")
    def list(self, gid, sid):
        last_system_oid = self.retrieve_last_system_oid()

        db_disp_res = None
        params = None
        if self.manager and self.manager.db_res:
            db_disp_res = ", ".join(
                ['%s'] * len(self.manager.db_res.split(','))
            )
            params = tuple(self.manager.db_res.split(','))

        SQL = render_template(
            "/".join([self.template_path, 'properties.sql']),
            conn=self.conn,
            last_system_oid=last_system_oid,
            db_restrictions=db_disp_res
        )
        status, res = self.conn.execute_dict(SQL, params)

        if not status:
            return internal_server_error(errormsg=res)

        for row in res['rows']:
            if self.manager.db == row['name']:
                row['canDrop'] = False
            else:
                conn = self.manager.connection(row['name'], did=row['did'])
                row['canDrop'] = True

        return ajax_response(
            response=res['rows'],
            status=200
        )

    def retrieve_last_system_oid(self):
        last_system_oid = 0
        if self.blueprint.show_system_objects:
            last_system_oid = 0
        elif (
            self.manager.db_info is not None and
            self.manager.did in self.manager.db_info
        ):
            last_system_oid = (self.manager.db_info[self.manager.did])[
                'datlastsysoid']
        return last_system_oid

    def get_nodes(self, gid, sid, show_system_templates=False):
        res = []
        last_system_oid = self.retrieve_last_system_oid()
        server_node_res = self.manager

        db_disp_res = None
        params = None
        if server_node_res and server_node_res.db_res:
            db_disp_res = ", ".join(
                ['%s'] * len(server_node_res.db_res.split(','))
            )
            params = tuple(server_node_res.db_res.split(','))
        SQL = render_template(
            "/".join([self.template_path, 'nodes.sql']),
            last_system_oid=last_system_oid,
            db_restrictions=db_disp_res
        )
        status, rset = self.conn.execute_dict(SQL, params)

        if not status:
            return internal_server_error(errormsg=rset)

        for row in rset['rows']:
            dbname = row['name']
            if self.manager.db == dbname:
                connected = True
                canDrop = canDisConn = False
            else:
                conn = self.manager.connection(dbname, did=row['did'])
                connected = conn.connected()
                canDrop = canDisConn = True

            res.append(
                self.blueprint.generate_browser_node(
                    row['did'],
                    sid,
                    row['name'],
                    icon="icon-database-not-connected" if not connected
                    else "pg-icon-database",
                    connected=connected,
                    tablespace=row['spcname'],
                    allowConn=row['datallowconn'],
                    canCreate=row['cancreate'],
                    canDisconn=canDisConn,
                    canDrop=canDrop,
                    inode=True if row['datallowconn'] else False
                )
            )

        return res

    @check_precondition(action="nodes")
    def nodes(self, gid, sid):
        res = self.get_nodes(gid, sid)

        return make_json_response(
            data=res,
            status=200
        )

    @check_precondition(action="get_databases")
    def get_databases(self, gid, sid):
        """
        This function is used to get all the databases irrespective of
        show_system_object flag for templates in create database dialog.
        :param gid:
        :param sid:
        :return:
        """
        res = []
        SQL = render_template(
            "/".join([self.template_path, 'nodes.sql']),
            last_system_oid=0,
        )
        status, rset = self.conn.execute_dict(SQL)

        if not status:
            return internal_server_error(errormsg=rset)

        for row in rset['rows']:
            res.append(row['name'])

        return make_json_response(
            data=res,
            status=200
        )

    @check_precondition(action="node")
    def node(self, gid, sid, did):
        SQL = render_template(
            "/".join([self.template_path, 'nodes.sql']),
            did=did, conn=self.conn, last_system_oid=0
        )
        status, rset = self.conn.execute_2darray(SQL)

        if not status:
            return internal_server_error(errormsg=rset)

        for row in rset['rows']:
            db = row['name']
            if self.manager.db == db:
                connected = True
            else:
                conn = self.manager.connection(row['name'])
                connected = conn.connected()
            icon_css_class = "pg-icon-database"
            if not connected:
                icon_css_class = "icon-database-not-connected"
            return make_json_response(
                data=self.blueprint.generate_browser_node(
                    row['did'],
                    sid,
                    row['name'],
                    icon=icon_css_class,
                    connected=connected,
                    spcname=row['spcname'],
                    allowConn=row['datallowconn'],
                    canCreate=row['cancreate']
                ),
                status=200
            )

        return gone(errormsg=_("Could not find the database on the server."))

    @check_precondition(action="properties")
    def properties(self, gid, sid, did):

        SQL = render_template(
            "/".join([self.template_path, 'properties.sql']),
            did=did, conn=self.conn, last_system_oid=0
        )
        status, res = self.conn.execute_dict(SQL)

        if not status:
            return internal_server_error(errormsg=res)

        if len(res['rows']) == 0:
            return gone(
                _("Could not find the database on the server.")
            )

        SQL = render_template(
            "/".join([self.template_path, 'acl.sql']),
            did=did, conn=self.conn
        )
        status, dataclres = self.conn.execute_dict(SQL)
        if not status:
            return internal_server_error(errormsg=res)

        res = self.formatdbacl(res, dataclres['rows'])

        SQL = render_template(
            "/".join([self.template_path, 'defacl.sql']),
            did=did, conn=self.conn
        )
        status, defaclres = self.conn.execute_dict(SQL)
        if not status:
            return internal_server_error(errormsg=res)

        res = self.formatdbacl(res, defaclres['rows'])

        result = res['rows'][0]
        result['is_sys_obj'] = (
            result['oid'] <= self.datlastsysoid)
        # Fetching variable for database
        SQL = render_template(
            "/".join([self.template_path, 'get_variables.sql']),
            did=did, conn=self.conn
        )

        status, res1 = self.conn.execute_dict(SQL)

        if not status:
            return internal_server_error(errormsg=res1)

        # Get Formatted Security Labels
        if 'seclabels' in result:
            # Security Labels is not available for PostgreSQL <= 9.1
            frmtd_sec_labels = parse_sec_labels_from_db(result['seclabels'])
            result.update(frmtd_sec_labels)

        # Get Formatted Variables
        frmtd_variables = parse_variables_from_db(res1['rows'])
        result.update(frmtd_variables)

        return ajax_response(
            response=result,
            status=200
        )

    @staticmethod
    def formatdbacl(res, dbacl):
        for row in dbacl:
            priv = parse_priv_from_db(row)
            res['rows'][0].setdefault(row['deftype'], []).append(priv)
        return res

    def connect(self, gid, sid, did):
        """Connect the Database."""
        from pgadmin.utils.driver import get_driver
        manager = get_driver(PG_DEFAULT_DRIVER).connection_manager(sid)
        conn = manager.connection(did=did, auto_reconnect=True)
        already_connected = conn.connected()
        if not already_connected:
            status, errmsg = conn.connect()
            if not status:
                current_app.logger.error(
                    "Could not connected to database(#{0}).\nError: {1}"
                    .format(
                        did, errmsg
                    )
                )
                return internal_server_error(errmsg)
            else:
                current_app.logger.info(
                    'Connection Established for Database Id: \
                    %s' % (did)
                )
        return make_json_response(
            success=1,
            info=_("Database connected."),
            data={
                'icon': 'pg-icon-database',
                'already_connected': already_connected,
                'connected': True,
                'info_prefix': '{0}/{1}'.
                format(Server.query.filter_by(id=sid)[0].name, conn.db)
            }
        )

    def disconnect(self, gid, sid, did):
        """Disconnect the database."""

        # Release Connection
        from pgadmin.utils.driver import get_driver
        manager = get_driver(PG_DEFAULT_DRIVER).connection_manager(sid)
        conn = manager.connection(did=did, auto_reconnect=True)
        status = manager.release(did=did)

        if not status:
            return unauthorized(_("Database could not be disconnected."))
        else:
            return make_json_response(
                success=1,
                info=_("Database disconnected."),
                data={
                    'icon': 'icon-database-not-connected',
                    'connected': False,
                    'info_prefix': '{0}/{1}'.
                    format(Server.query.filter_by(id=sid)[0].name, conn.db)
                }
            )

    @check_precondition(action="get_encodings")
    def get_encodings(self, gid, sid, did=None):
        """
        This function to return list of avialable encodings
        """
        res = [{'label': '', 'value': ''}]
        SQL = render_template(
            "/".join([self.template_path, 'get_encodings.sql'])
        )
        status, rset = self.conn.execute_dict(SQL)
        if not status:
            return internal_server_error(errormsg=rset)

        for row in rset['rows']:
            res.append(
                {'label': row['encoding'], 'value': row['encoding']}
            )

        return make_json_response(
            data=res,
            status=200
        )

    @check_precondition(action="get_ctypes")
    def get_ctypes(self, gid, sid, did=None):
        """
        This function to return list of available collation/character types
        """
        res = [{'label': '', 'value': ''}]
        default_list = ['C', 'POSIX']
        for val in default_list:
            res.append(
                {'label': val, 'value': val}
            )
        SQL = render_template(
            "/".join([self.template_path, 'get_ctypes.sql'])
        )
        status, rset = self.conn.execute_dict(SQL)
        if not status:
            return internal_server_error(errormsg=rset)

        for row in rset['rows']:
            if row['cname'] not in default_list:
                res.append({'label': row['cname'], 'value': row['cname']})

        return make_json_response(
            data=res,
            status=200
        )

    @check_precondition(action="create")
    def create(self, gid, sid):
        """Create the database."""
        required_args = [
            u'name'
        ]

        data = request.form if request.form else json.loads(
            request.data, encoding='utf-8'
        )

        for arg in required_args:
            if arg not in data:
                return make_json_response(
                    status=410,
                    success=0,
                    errormsg=_(
                        "Could not find the required parameter ({})."
                    ).format(arg)
                )
        # The below SQL will execute CREATE DDL only
        SQL = render_template(
            "/".join([self.template_path, 'create.sql']),
            data=data, conn=self.conn
        )
        status, msg = self.conn.execute_scalar(SQL)
        if not status:
            return internal_server_error(errormsg=msg)

        if 'datacl' in data:
            data['datacl'] = parse_priv_to_db(data['datacl'], 'DATABASE')

        # The below SQL will execute rest DMLs because we cannot execute
        # CREATE with any other
        SQL = render_template(
            "/".join([self.template_path, 'grant.sql']),
            data=data, conn=self.conn
        )
        SQL = SQL.strip('\n').strip(' ')
        if SQL and SQL != "":
            status, msg = self.conn.execute_scalar(SQL)
            if not status:
                return internal_server_error(errormsg=msg)

        # We need oid of newly created database
        SQL = render_template(
            "/".join([self.template_path, 'properties.sql']),
            name=data['name'], conn=self.conn, last_system_oid=0
        )
        SQL = SQL.strip('\n').strip(' ')
        if SQL and SQL != "":
            status, res = self.conn.execute_dict(SQL)
            if not status:
                return internal_server_error(errormsg=res)

        response = res['rows'][0]

        return jsonify(
            node=self.blueprint.generate_browser_node(
                response['did'],
                sid,
                response['name'],
                icon="icon-database-not-connected",
                connected=False,
                tablespace=response['default_tablespace'],
                allowConn=True,
                canCreate=response['cancreate'],
                canDisconn=True,
                canDrop=True
            )
        )

    @check_precondition(action='update')
    def update(self, gid, sid, did):
        """Update the database."""

        data = request.form if request.form else json.loads(
            request.data, encoding='utf-8'
        )

        # Generic connection for offline updates
        conn = self.manager.connection(conn_id='db_offline_update')
        status, errmsg = conn.connect()
        if not status:
            current_app.logger.error(
                "Could not create database connection for offline updates\n"
                "Err: {0}".format(errmsg)
            )
            return internal_server_error(errmsg)

        if did is not None:
            # Fetch the name of database for comparison
            status, rset = self.conn.execute_dict(
                render_template(
                    "/".join([self.template_path, 'nodes.sql']),
                    did=did, conn=self.conn, last_system_oid=0
                )
            )
            if not status:
                return internal_server_error(errormsg=rset)

            if len(rset['rows']) == 0:
                return gone(
                    _('Could not find the database on the server.')
                )

            data['old_name'] = (rset['rows'][0])['name']
            if 'name' not in data:
                data['name'] = data['old_name']

        # Release any existing connection from connection manager
        # to perform offline operation
        self.manager.release(did=did)

        for action in ["rename_database", "tablespace"]:
            SQL = self.get_offline_sql(gid, sid, data, did, action)
            SQL = SQL.strip('\n').strip(' ')
            if SQL and SQL != "":
                status, msg = conn.execute_scalar(SQL)
                if not status:
                    # In case of error from server while rename it,
                    # reconnect to the database with old name again.
                    self.conn = self.manager.connection(
                        database=data['old_name'], auto_reconnect=True
                    )
                    status, errmsg = self.conn.connect()
                    if not status:
                        current_app.logger.error(
                            'Could not reconnected to database(#{0}).\n'
                            'Error: {1}'.format(did, errmsg)
                        )
                    return internal_server_error(errormsg=msg)

                QueryHistory.update_history_dbname(
                    current_user.id, sid, data['old_name'], data['name'])
        # Make connection for database again
        if self._db['datallowconn']:
            self.conn = self.manager.connection(
                database=data['name'], auto_reconnect=True
            )
            status, errmsg = self.conn.connect()

            if not status:
                current_app.logger.error(
                    'Could not connected to database(#{0}).\n'
                    'Error: {1}'.format(did, errmsg)
                )
                return internal_server_error(errmsg)

        SQL = self.get_online_sql(gid, sid, data, did)
        SQL = SQL.strip('\n').strip(' ')
        if SQL and SQL != "":
            status, msg = self.conn.execute_scalar(SQL)
            if not status:
                return internal_server_error(errormsg=msg)

        # Release any existing connection from connection manager
        # used for offline updates
        self.manager.release(conn_id="db_offline_update")

        # Fetch the new data again after update for proper node
        # generation
        status, rset = self.conn.execute_dict(
            render_template(
                "/".join([self.template_path, 'nodes.sql']),
                did=did, conn=self.conn, last_system_oid=0
            )
        )
        if not status:
            return internal_server_error(errormsg=rset)

        if len(rset['rows']) == 0:
            return gone(
                _("Could not find the database on the server.")
            )

        res = rset['rows'][0]

        canDrop = canDisConn = True
        if self.manager.db == res['name']:
            canDrop = canDisConn = False

        return jsonify(
            node=self.blueprint.generate_browser_node(
                did,
                sid,
                res['name'],
                icon="pg-icon-{0}".format(self.node_type) if
                self._db['datallowconn'] and self.conn.connected() else
                "icon-database-not-connected",
                connected=self.conn.connected() if
                self._db['datallowconn'] else False,
                tablespace=res['spcname'],
                allowConn=res['datallowconn'],
                canCreate=res['cancreate'],
                canDisconn=canDisConn,
                canDrop=canDrop,
                inode=True if res['datallowconn'] else False
            )
        )

    @check_precondition(action="drop")
    def delete(self, gid, sid, did=None):
        """Delete the database."""

        if did is None:
            data = request.form if request.form else json.loads(
                request.data, encoding='utf-8'
            )
        else:
            data = {'ids': [did]}

        for did in data['ids']:
            default_conn = self.manager.connection()
            SQL = render_template(
                "/".join([self.template_path, 'delete.sql']),
                did=did, conn=self.conn
            )
            status, res = default_conn.execute_scalar(SQL)
            if not status:
                return internal_server_error(errormsg=res)

            if res is None:
                return make_json_response(
                    status=410,
                    success=0,
                    errormsg=_(
                        'Error: Object not found.'
                    ),
                    info=_(
                        'The specified database could not be found.\n'
                    )
                )
            else:

                status = self.manager.release(did=did)

                SQL = render_template(
                    "/".join([self.template_path, 'delete.sql']),
                    datname=res, conn=self.conn
                )

                status, msg = default_conn.execute_scalar(SQL)
                if not status:
                    # reconnect if database drop failed.
                    conn = self.manager.connection(did=did,
                                                   auto_reconnect=True)
                    status, errmsg = conn.connect()

                    return internal_server_error(errormsg=msg)

        return make_json_response(success=1)

    @check_precondition(action="msql")
    def msql(self, gid, sid, did=None):
        """
        This function to return modified SQL.
        """
        data = {}
        for k, v in request.args.items():
            try:
                # comments should be taken as is because if user enters a
                # json comment it is parsed by loads which should not happen
                if k in ('comments',):
                    data[k] = v
                else:
                    data[k] = json.loads(v, encoding='utf-8')
            except ValueError:
                data[k] = v
        status, res = self.get_sql(gid, sid, data, did)

        if not status:
            return res

        res = re.sub('\n{2,}', '\n\n', res)
        SQL = res.strip('\n').strip(' ')

        return make_json_response(
            data=SQL,
            status=200
        )

    def get_sql(self, gid, sid, data, did=None):
        SQL = ''
        if did is not None:
            # Fetch the name of database for comparison
            conn = self.manager.connection()
            status, rset = conn.execute_dict(
                render_template(
                    "/".join([self.template_path, 'nodes.sql']),
                    did=did, conn=conn, last_system_oid=0
                )
            )
            if not status:
                return False, internal_server_error(errormsg=rset)

            if len(rset['rows']) == 0:
                return gone(
                    _("Could not find the database on the server.")
                )

            data['old_name'] = (rset['rows'][0])['name']
            if 'name' not in data:
                data['name'] = data['old_name']

            SQL = ''
            for action in ["rename_database", "tablespace"]:
                SQL += self.get_offline_sql(gid, sid, data, did, action)

            SQL += self.get_online_sql(gid, sid, data, did)
        else:
            SQL += self.get_new_sql(gid, sid, data, did)

        return True, SQL

    def get_new_sql(self, gid, sid, data, did=None):
        """
        Generates sql for creating new database.
        """
        required_args = [
            u'name'
        ]

        for arg in required_args:
            if arg not in data:
                return _(" -- definition incomplete")

        acls = []
        SQL_acl = ''

        try:
            acls = render_template(
                "/".join([self.template_path, 'allowed_privs.json'])
            )
            acls = json.loads(acls, encoding='utf-8')
        except Exception as e:
            current_app.logger.exception(e)

        # Privileges
        for aclcol in acls:
            if aclcol in data:
                allowedacl = acls[aclcol]
                data[aclcol] = parse_priv_to_db(
                    data[aclcol], allowedacl['acl']
                )

        SQL_acl = render_template(
            "/".join([self.template_path, 'grant.sql']),
            data=data,
            conn=self.conn
        )

        SQL = render_template(
            "/".join([self.template_path, 'create.sql']),
            data=data, conn=self.conn
        )
        SQL += "\n"
        SQL += SQL_acl
        return SQL

    def get_online_sql(self, gid, sid, data, did=None):
        """
        Generates sql for altering database which don not require
        database to be disconnected before applying.
        """
        acls = []
        try:
            acls = render_template(
                "/".join([self.template_path, 'allowed_privs.json'])
            )
            acls = json.loads(acls, encoding='utf-8')
        except Exception as e:
            current_app.logger.exception(e)

        # Privileges
        for aclcol in acls:
            if aclcol in data:
                allowedacl = acls[aclcol]

                for key in ['added', 'changed', 'deleted']:
                    if key in data[aclcol]:
                        data[aclcol][key] = parse_priv_to_db(
                            data[aclcol][key], allowedacl['acl']
                        )

        return render_template(
            "/".join([self.template_path, 'alter_online.sql']),
            data=data, conn=self.conn
        )

    def get_offline_sql(self, gid, sid, data, did=None, action=None):
        """
        Generates sql for altering database which require
        database to be disconnected before applying.
        """

        return render_template(
            "/".join([self.template_path, 'alter_offline.sql']),
            data=data, conn=self.conn, action=action
        )

    @check_precondition(action="variable_options")
    def variable_options(self, gid, sid):
        SQL = render_template(
            "/".join([self.template_path, 'variables.sql'])
        )
        status, rset = self.conn.execute_dict(SQL)

        if not status:
            return internal_server_error(errormsg=rset)

        return make_json_response(
            data=rset['rows'],
            status=200
        )

    @check_precondition()
    def statistics(self, gid, sid, did=None):
        """
        statistics
        Returns the statistics for a particular database if did is specified,
        otherwise it will return statistics for all the databases in that
        server.
        """
        last_system_oid = self.retrieve_last_system_oid()

        db_disp_res = None
        params = None
        if self.manager and self.manager.db_res:
            db_disp_res = ", ".join(
                ['%s'] * len(self.manager.db_res.split(','))
            )
            params = tuple(self.manager.db_res.split(','))

        conn = self.manager.connection()
        status, res = conn.execute_dict(render_template(
            "/".join([self.template_path, 'stats.sql']),
            did=did,
            conn=conn,
            last_system_oid=last_system_oid,
            db_restrictions=db_disp_res),
            params
        )

        if not status:
            return internal_server_error(errormsg=res)

        return make_json_response(
            data=res,
            status=200
        )

    @check_precondition(action="sql")
    def sql(self, gid, sid, did):
        """
        This function will generate sql for sql panel
        """

        conn = self.manager.connection()
        SQL = render_template(
            "/".join([self.template_path, 'properties.sql']),
            did=did, conn=conn, last_system_oid=0
        )
        status, res = conn.execute_dict(SQL)

        if not status:
            return internal_server_error(errormsg=res)

        if len(res['rows']) == 0:
            return gone(
                _("Could not find the database on the server.")
            )

        SQL = render_template(
            "/".join([self.template_path, 'acl.sql']),
            did=did, conn=self.conn
        )
        status, dataclres = self.conn.execute_dict(SQL)
        if not status:
            return internal_server_error(errormsg=dataclres)
        res = self.formatdbacl(res, dataclres['rows'])

        SQL = render_template(
            "/".join([self.template_path, 'defacl.sql']),
            did=did, conn=self.conn
        )
        status, defaclres = self.conn.execute_dict(SQL)
        if not status:
            return internal_server_error(errormsg=defaclres)

        res = self.formatdbacl(res, defaclres['rows'])

        result = res['rows'][0]

        SQL = render_template(
            "/".join([self.template_path, 'get_variables.sql']),
            did=did, conn=self.conn
        )
        status, res1 = self.conn.execute_dict(SQL)
        if not status:
            return internal_server_error(errormsg=res1)

        # Get Formatted Security Labels
        if 'seclabels' in result:
            # Security Labels is not available for PostgreSQL <= 9.1
            frmtd_sec_labels = parse_sec_labels_from_db(result['seclabels'])
            result.update(frmtd_sec_labels)

        # Get Formatted Variables
        frmtd_variables = parse_variables_from_db(res1['rows'])
        result.update(frmtd_variables)

        sql_header = u"-- Database: {0}\n\n-- ".format(result['name'])

        sql_header += render_template(
            "/".join([self.template_path, 'delete.sql']),
            datname=result['name'], conn=conn
        )

        SQL = self.get_new_sql(gid, sid, result, did)
        SQL = re.sub('\n{2,}', '\n\n', SQL)
        SQL = sql_header + '\n' + SQL
        SQL = SQL.strip('\n')

        return ajax_response(response=SQL)

    @check_precondition()
    def dependents(self, gid, sid, did):
        """
        This function gets the dependents and returns an ajax response
        for the database.

        Args:
            gid: Server Group ID
            sid: Server ID
            did: Database ID
        """
        dependents_result = self.get_dependents(self.conn, did) if \
            self.conn.connected() else []
        return ajax_response(
            response=dependents_result,
            status=200
        )

    @check_precondition()
    def dependencies(self, gid, sid, did):
        """
        This function gets the dependencies and returns an ajax response
        for the database.

        Args:
            gid: Server Group ID
            sid: Server ID
            did: Database ID
        """
        dependencies_result = self.get_dependencies(self.conn, did) if \
            self.conn.connected() else []
        return ajax_response(
            response=dependencies_result,
            status=200
        )


SchemaDiffRegistry(blueprint.node_type, DatabaseView)
DatabaseView.register_node_view(blueprint)
