#    Copyright (c) 2013 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import json
import logging
import os
import re
import shutil
import StringIO
import sys
import tempfile

import fixtures
import mock
import requests_mock
import six
from testtools import matchers

from muranoclient.common import exceptions as common_exceptions
from muranoclient.common import utils
from muranoclient.openstack.common.apiclient import exceptions
import muranoclient.shell
from muranoclient.tests import base
from muranoclient.tests import test_utils
from muranoclient.v1 import shell as v1_shell

make_pkg = test_utils.make_pkg

FIXTURE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                           'fixture_data'))
# RESULT_PACKAGE = os.path.join(FIXTURE_DIR, 'test-app.zip')

FAKE_ENV = {'OS_USERNAME': 'username',
            'OS_PASSWORD': 'password',
            'OS_TENANT_NAME': 'tenant_name',
            'OS_AUTH_URL': 'http://no.where'}

FAKE_ENV2 = {'OS_USERNAME': 'username',
             'OS_PASSWORD': 'password',
             'OS_TENANT_ID': 'tenant_id',
             'OS_AUTH_URL': 'http://no.where'}


class TestArgs(object):
    version = ''
    murano_repo_url = 'http://127.0.0.1'
    exists_action = ''
    is_public = False
    categories = []


class ShellTest(base.TestCaseShell):

    def make_env(self, exclude=None, fake_env=FAKE_ENV):
        env = dict((k, v) for k, v in fake_env.items() if k != exclude)
        self.useFixture(fixtures.MonkeyPatch('os.environ', env))

    def setUp(self):
        super(ShellTest, self).setUp()
        self.useFixture(fixtures.MonkeyPatch(
            'keystoneclient.v2_0.client.Client', mock.MagicMock))
        self.client = mock.MagicMock()

        # We don't set an endpoint (client.service_catalog.url_for is a mock)
        # and get_proxy_url doesn't like that. We don't care about testing
        # that functionality, so mock it out.
        self.useFixture(fixtures.MonkeyPatch(
            'muranoclient.common.http.HTTPClient.get_proxy_url',
            mock.MagicMock))

        # To prevent log descriptors from being closed during
        # shell tests set a custom StreamHandler
        self.logger = logging.getLogger()
        self.logger.level = logging.DEBUG
        self.stream_handler = logging.StreamHandler(sys.stdout)
        self.logger.addHandler(self.stream_handler)

    def tearDown(self):
        super(ShellTest, self).tearDown()
        self.logger.removeHandler(self.stream_handler)

    def shell(self, argstr, exitcodes=(0,)):
        orig = sys.stdout
        orig_stderr = sys.stderr
        try:
            sys.stdout = six.StringIO()
            sys.stderr = six.StringIO()
            _shell = muranoclient.shell.MuranoShell()
            _shell.main(argstr.split())
        except SystemExit:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            self.assertIn(exc_value.code, exitcodes)
        finally:
            stdout = sys.stdout.getvalue()
            sys.stdout.close()
            sys.stdout = orig
            stderr = sys.stderr.getvalue()
            sys.stderr.close()
            sys.stderr = orig_stderr
        return (stdout, stderr)

    def test_help_unknown_command(self):
        self.assertRaises(exceptions.CommandError, self.shell, 'help foofoo')

    def test_help(self):
        required = [
            '.*?^usage: murano',
            '.*?^\s+package-create\s+Create an application package.',
            '.*?^See "murano help COMMAND" for help on a specific command',
        ]
        stdout, stderr = self.shell('help')
        for r in required:
            self.assertThat((stdout + stderr),
                            matchers.MatchesRegex(r, re.DOTALL | re.MULTILINE))

    def test_help_on_subcommand(self):
        required = [
            '.*?^usage: murano package-create',
            '.*?^Create an application package.',
        ]
        stdout, stderr = self.shell('help package-create')
        for r in required:
            self.assertThat((stdout + stderr),
                            matchers.MatchesRegex(r, re.DOTALL | re.MULTILINE))

    def test_help_no_options(self):
        required = [
            '.*?^usage: murano',
            '.*?^\s+package-create\s+Create an application package',
            '.*?^See "murano help COMMAND" for help on a specific command',
        ]
        stdout, stderr = self.shell('')
        for r in required:
            self.assertThat((stdout + stderr),
                            matchers.MatchesRegex(r, re.DOTALL | re.MULTILINE))

    def test_no_username(self):
        required = ('You must provide a username via either --os-username or '
                    'env[OS_USERNAME] or a token via --os-auth-token or '
                    'env[OS_AUTH_TOKEN]',)
        self.make_env(exclude='OS_USERNAME')
        try:
            self.shell('package-list')
        except exceptions.CommandError as message:
            self.assertEqual(required, message.args)
        else:
            self.fail('CommandError not raised')

    def test_no_tenant_name(self):
        required = ('You must provide a tenant name '
                    'or tenant id via --os-tenant-name, '
                    '--os-tenant-id, env[OS_TENANT_NAME] '
                    'or env[OS_TENANT_ID]',)
        self.make_env(exclude='OS_TENANT_NAME')
        try:
            self.shell('package-list')
        except exceptions.CommandError as message:
            self.assertEqual(required, message.args)
        else:
            self.fail('CommandError not raised')

    def test_no_tenant_id(self):
        required = ('You must provide a tenant name '
                    'or tenant id via --os-tenant-name, '
                    '--os-tenant-id, env[OS_TENANT_NAME] '
                    'or env[OS_TENANT_ID]',)
        self.make_env(exclude='OS_TENANT_ID', fake_env=FAKE_ENV2)
        try:
            self.shell('package-list')
        except exceptions.CommandError as message:
            self.assertEqual(required, message.args)
        else:
            self.fail('CommandError not raised')

    def test_no_auth_url(self):
        required = ('You must provide an auth url'
                    ' via either --os-auth-url or via env[OS_AUTH_URL]',)
        self.make_env(exclude='OS_AUTH_URL')
        try:
            self.shell('package-list')
        except exceptions.CommandError as message:
            self.assertEqual(required, message.args)
        else:
            self.fail('CommandError not raised')

    @mock.patch('muranoclient.v1.packages.PackageManager')
    def test_package_list(self, mock_package_manager):
        self.client.packages = mock_package_manager()
        self.make_env()
        self.shell('package-list')
        self.client.packages.filter.assert_called_once_with(
            include_disabled=False)

    @mock.patch('muranoclient.v1.packages.PackageManager')
    def test_package_show(self, mock_package_manager):
        self.client.packages = mock_package_manager()
        mock_package = mock.MagicMock()
        mock_package.class_definitions = ''
        mock_package.categories = ''
        mock_package.tags = ''
        mock_package.description = ''
        self.client.packages.get.return_value = mock_package
        self.make_env()
        self.shell('package-show 1234')
        self.client.packages.get.assert_called_with('1234')

    @mock.patch('muranoclient.v1.packages.PackageManager')
    def test_package_delete(self, mock_package_manager):
        self.client.packages = mock_package_manager()
        self.make_env()
        self.shell('package-delete 1234')
        self.client.packages.delete.assert_called_with('1234')

    @mock.patch('muranoclient.v1.environments.EnvironmentManager')
    def test_environment_delete(self, mock_manager):
        self.client.environments = mock_manager()
        self.make_env()
        self.shell('environment-delete env1 env2')
        self.client.environments.find.assert_has_calls([
            mock.call(name='env1'), mock.call(name='env2')])
        self.client.environments.delete.assert_called_twice()

    @mock.patch('muranoclient.v1.environments.EnvironmentManager')
    def test_environment_rename(self, mock_manager):
        self.client.environments = mock_manager()
        self.make_env()
        self.shell('environment-rename old-name-or-id new-name')
        self.client.environments.find.assert_called_once_with(
            name='old-name-or-id')
        self.client.environments.update.assert_called_once()

    @mock.patch('muranoclient.v1.environments.EnvironmentManager')
    def test_environment_show(self, mock_manager):
        self.client.environments = mock_manager()
        self.make_env()
        self.shell('environment-show env-id-or-name')
        self.client.environments.find.assert_called_once_with(
            name='env-id-or-name')
        self.client.environments.get.assert_called_once()

    @mock.patch('muranoclient.v1.templates.EnvTemplateManager')
    def test_env_template_delete(self, mock_manager):
        self.client.env_templates = mock_manager()
        self.make_env()
        self.shell('env-template-delete env1 env2')
        self.client.env_templates.delete.assert_has_calls([
            mock.call('env1'), mock.call('env2')])

    @mock.patch('muranoclient.v1.templates.EnvTemplateManager')
    def test_env_template_create(self, mock_manager):
        self.client.env_templates = mock_manager()
        self.make_env()
        self.shell('env-template-create env-name')
        self.client.env_templates.create.assert_called_once_with(
            {'name': 'env-name'})

    @mock.patch('muranoclient.v1.templates.EnvTemplateManager')
    def test_env_template_show(self, mock_manager):
        self.client.env_templates = mock_manager()
        self.make_env()
        self.shell('env-template-show env-id')
        self.client.env_templates.get.assert_called_once_with('env-id')

    @mock.patch('muranoclient.v1.environments.EnvironmentManager')
    @mock.patch('muranoclient.v1.deployments.DeploymentManager')
    def test_deployments_show(self, mock_deployment_manager, mock_env_manager):
        self.client.deployments = mock_deployment_manager()
        self.client.environments = mock_env_manager()
        self.make_env()
        self.shell('deployment-list env-id-or-name')
        self.client.environments.find.assert_called_once_with(
            name='env-id-or-name')
        self.client.deployments.list.assert_called_once()


class ShellPackagesOperations(ShellTest):

    def test_create_hot_based_package(self):
        self.useFixture(fixtures.MonkeyPatch(
            'muranoclient.v1.client.Client', mock.MagicMock))
        heat_template = os.path.join(FIXTURE_DIR, 'heat-template.yaml')
        logo = os.path.join(FIXTURE_DIR, 'logo.png')
        self.make_env()
        with tempfile.NamedTemporaryFile() as f:
            RESULT_PACKAGE = f.name
            c = "package-create --template={0} --output={1} -l={2}".format(
                heat_template, RESULT_PACKAGE, logo)
            stdout, stderr = self.shell(c)
            matchers.MatchesRegex((stdout + stderr),
                                  "Application package "
                                  "is available at {0}".format(RESULT_PACKAGE))

    def test_create_mpl_package(self):
        self.useFixture(fixtures.MonkeyPatch(
            'muranoclient.v1.client.Client', mock.MagicMock))
        classes_dir = os.path.join(FIXTURE_DIR, 'test-app', 'Classes')
        resources_dir = os.path.join(FIXTURE_DIR, 'test-app', 'Resources')
        ui = os.path.join(FIXTURE_DIR, 'test-app', 'ui.yaml')
        self.make_env()
        with tempfile.NamedTemporaryFile() as f:
            RESULT_PACKAGE = f.name
            stdout, stderr = self.shell(
                "package-create  -c={0} -r={1} -u={2} -o={3}".format(
                    classes_dir, resources_dir, ui, RESULT_PACKAGE))
            matchers.MatchesRegex((stdout + stderr),
                                  "Application package "
                                  "is available at {0}".format(RESULT_PACKAGE))

    @mock.patch('muranoclient.common.utils.Package.from_file')
    def test_package_import(self, from_file):
        args = TestArgs()
        with tempfile.NamedTemporaryFile() as f:
            RESULT_PACKAGE = f.name
            args.filename = RESULT_PACKAGE
            args.categories = ['Cat1', 'Cat2 with space']
            args.is_public = True

            pkg = make_pkg({'FullName': RESULT_PACKAGE})
            from_file.return_value = utils.Package(utils.File(pkg))

            v1_shell.do_package_import(self.client, args)

            self.client.packages.create.assert_called_once_with({
                'categories': ['Cat1', 'Cat2 with space'],
                'is_public': True
            }, {RESULT_PACKAGE: mock.ANY},)

    def _test_conflict(self,
                       packages, from_file, raw_input_mock,
                       input_action, exists_action=''):
        packages.create = mock.MagicMock(
            side_effect=[common_exceptions.HTTPConflict("Conflict"), None])

        packages.filter.return_value = [mock.Mock(id='test_id')]

        raw_input_mock.return_value = input_action
        args = TestArgs()
        args.exists_action = exists_action
        with tempfile.NamedTemporaryFile() as f:
            args.filename = f.name

            pkg = make_pkg({'FullName': f.name})
            from_file.return_value = utils.Package(utils.File(pkg))

            v1_shell.do_package_import(self.client, args)
            return f.name

    @mock.patch('__builtin__.raw_input')
    @mock.patch('muranoclient.common.utils.Package.from_file')
    def test_package_import_conflict_skip(self, from_file, raw_input_mock):

        name = self._test_conflict(
            self.client.packages,
            from_file,
            raw_input_mock,
            's',
        )

        self.client.packages.create.assert_called_once_with({
            'is_public': False,
        }, {name: mock.ANY},)

    @mock.patch('__builtin__.raw_input')
    @mock.patch('muranoclient.common.utils.Package.from_file')
    def test_package_import_conflict_skip_ea(self, from_file, raw_input_mock):

        name = self._test_conflict(
            self.client.packages,
            from_file,
            raw_input_mock,
            '',
            exists_action='s',
        )

        self.client.packages.create.assert_called_once_with({
            'is_public': False,
        }, {name: mock.ANY},)
        self.assertFalse(raw_input_mock.called)

    @mock.patch('__builtin__.raw_input')
    @mock.patch('muranoclient.common.utils.Package.from_file')
    def test_package_import_conflict_abort(self, from_file, raw_input_mock):

        self.assertRaises(SystemExit, self._test_conflict,
                          self.client.packages,
                          from_file,
                          raw_input_mock,
                          'a',
                          )

        self.client.packages.create.assert_called_once_with({
            'is_public': False,
        }, mock.ANY,)

    @mock.patch('__builtin__.raw_input')
    @mock.patch('muranoclient.common.utils.Package.from_file')
    def test_package_import_conflict_abort_ea(self,
                                              from_file, raw_input_mock):

        self.assertRaises(SystemExit, self._test_conflict,
                          self.client.packages,
                          from_file,
                          raw_input_mock,
                          '',
                          exists_action='a',
                          )

        self.client.packages.create.assert_called_once_with({
            'is_public': False,
        }, mock.ANY,)
        self.assertFalse(raw_input_mock.called)

    @mock.patch('__builtin__.raw_input')
    @mock.patch('muranoclient.common.utils.Package.from_file')
    def test_package_import_conflict_update(self, from_file, raw_input_mock):

        name = self._test_conflict(
            self.client.packages,
            from_file,
            raw_input_mock,
            'u',
        )

        self.client.packages.delete.assert_called_once_with('test_id')

        self.client.packages.create.assert_has_calls(
            [
                mock.call({'is_public': False}, {name: mock.ANY},),
                mock.call({'is_public': False}, {name: mock.ANY},)
            ], any_order=True,
        )
        self.assertEqual(self.client.packages.create.call_count, 2)

    @mock.patch('__builtin__.raw_input')
    @mock.patch('muranoclient.common.utils.Package.from_file')
    def test_package_import_conflict_update_ea(self,
                                               from_file, raw_input_mock):

        name = self._test_conflict(
            self.client.packages,
            from_file,
            raw_input_mock,
            '',
            exists_action='u',
        )

        self.client.packages.delete.assert_called_once_with('test_id')

        self.client.packages.create.assert_has_calls(
            [
                mock.call({'is_public': False}, {name: mock.ANY},),
                mock.call({'is_public': False}, {name: mock.ANY},)
            ], any_order=True,
        )
        self.assertEqual(self.client.packages.create.call_count, 2)
        self.assertFalse(raw_input_mock.called)

    @mock.patch('muranoclient.common.utils.Package.from_file')
    def test_package_import_no_categories(self, from_file):
        args = TestArgs()

        with tempfile.NamedTemporaryFile() as f:
            RESULT_PACKAGE = f.name
            pkg = make_pkg({'FullName': RESULT_PACKAGE})
            from_file.return_value = utils.Package(utils.File(pkg))

            args.filename = RESULT_PACKAGE
            args.categories = None
            args.is_public = False

            v1_shell.do_package_import(self.client, args)

            self.client.packages.create.assert_called_once_with(
                {'is_public': False},
                {RESULT_PACKAGE: mock.ANY},
            )

    @requests_mock.mock()
    @mock.patch('muranoclient.common.utils.Package.from_file')
    def test_package_import_url(self, rm, from_file):
        args = TestArgs()
        args.filename = "http://127.0.0.1/test_package.zip"
        args.categories = None
        args.is_public = False

        pkg = make_pkg({'FullName': 'test_package'})
        from_file.return_value = utils.Package(utils.File(pkg))

        rm.get(args.filename, body=make_pkg({'FullName': 'test_package'}))

        v1_shell.do_package_import(self.client, args)

        self.client.packages.create.assert_called_once_with(
            {'is_public': False},
            {'test_package': mock.ANY},
        )

    @requests_mock.mock()
    @mock.patch('muranoclient.common.utils.Package.from_file')
    def test_package_import_by_name(self, rm, from_file):
        args = TestArgs()

        args.filename = "io.test.apps.test_application"
        args.categories = None
        args.is_public = False
        args.murano_repo_url = "http://127.0.0.1"

        pkg = make_pkg({'FullName': args.filename})
        from_file.return_value = utils.Package(utils.File(pkg))

        rm.get(args.murano_repo_url + '/apps/' + args.filename + '.zip',
               body=make_pkg({'FullName': 'first_app'}))

        v1_shell.do_package_import(self.client, args)

        self.assertTrue(self.client.packages.create.called)
        self.client.packages.create.assert_called_once_with(
            {'is_public': False},
            {args.filename: mock.ANY},
        )

    @requests_mock.mock()
    def test_import_bundle_by_name(self, m):
        """Asserts bundle import calls packages create once for each pkg."""
        pkg1 = make_pkg({'FullName': 'first_app'})
        pkg2 = make_pkg({'FullName': 'second_app'})

        m.get(TestArgs.murano_repo_url + '/apps/first_app.zip', body=pkg1)
        m.get(TestArgs.murano_repo_url + '/apps/second_app.1.0.zip',
              body=pkg2)
        s = StringIO.StringIO()
        bundle_contents = {'Packages': [
            {'Name': 'first_app'},
            {'Name': 'second_app', 'Version': '1.0'}
        ]}
        json.dump(bundle_contents, s)
        s.seek(0)

        m.get(TestArgs.murano_repo_url + '/bundles/test_bundle.bundle',
              body=s)

        args = TestArgs()
        args.filename = "test_bundle"

        v1_shell.do_bundle_import(self.client, args)

        self.client.packages.create.assert_has_calls(
            [
                mock.call({'is_public': False}, {'first_app': mock.ANY}),
                mock.call({'is_public': False}, {'second_app': mock.ANY}),
            ], any_order=True,
        )

    @requests_mock.mock()
    def test_import_bundle_dependencies(self, m):
        """Asserts bundle import calls packages create once for each pkg,
        including dependencies.
        """
        pkg1 = make_pkg(
            {'FullName': 'first_app', 'Require': {'second_app': '1.0'}, })
        pkg2 = make_pkg({'FullName': 'second_app'})

        m.get(TestArgs.murano_repo_url + '/apps/first_app.zip', body=pkg1)
        m.get(TestArgs.murano_repo_url + '/apps/second_app.1.0.zip',
              body=pkg2)
        s = StringIO.StringIO()

        # bundle only contains 1st package
        bundle_contents = {'Packages': [
            {'Name': 'first_app'},
        ]}
        json.dump(bundle_contents, s)
        s.seek(0)

        m.get(TestArgs.murano_repo_url + '/bundles/test_bundle.bundle',
              body=s)

        args = TestArgs()
        args.filename = "test_bundle"

        v1_shell.do_bundle_import(self.client, args)

        self.client.packages.create.assert_has_calls(
            [
                mock.call({'is_public': False}, {'first_app': mock.ANY}),
                mock.call({'is_public': False}, {'second_app': mock.ANY}),
            ], any_order=True,
        )

    @requests_mock.mock()
    def test_import_bundle_by_url(self, m):
        """Asserts bundle import calls packages create once for each pkg."""
        pkg1 = make_pkg({'FullName': 'first_app'})
        pkg2 = make_pkg({'FullName': 'second_app'})

        m.get(TestArgs.murano_repo_url + '/apps/first_app.zip', body=pkg1)
        m.get(TestArgs.murano_repo_url + '/apps/second_app.1.0.zip',
              body=pkg2)
        s = StringIO.StringIO()
        bundle_contents = {'Packages': [
            {'Name': 'first_app'},
            {'Name': 'second_app', 'Version': '1.0'}
        ]}
        json.dump(bundle_contents, s)
        s.seek(0)

        url = 'http://127.0.0.2/test_bundle.bundle'
        m.get(url, body=s)

        args = TestArgs()
        args.filename = url

        v1_shell.do_bundle_import(self.client, args)

        self.client.packages.create.assert_has_calls(
            [
                mock.call({'is_public': False}, {'first_app': mock.ANY}),
                mock.call({'is_public': False}, {'second_app': mock.ANY}),
            ], any_order=True,
        )

    @requests_mock.mock()
    def test_import_bundle_wrong_url(self, m):
        url = 'http://127.0.0.2/test_bundle.bundle'
        m.get(url, status_code=404)

        args = TestArgs()
        args.filename = url

        v1_shell.do_bundle_import(self.client, args)
        self.assertFalse(self.client.packages.create.called)

    @requests_mock.mock()
    def test_import_bundle_no_bundle(self, m):
        url = 'http://127.0.0.1/bundles/test_bundle.bundle'
        m.get(url, status_code=404)

        args = TestArgs()
        args.filename = "test_bundle"

        v1_shell.do_bundle_import(self.client, args)
        self.assertFalse(self.client.packages.create.called)

    @requests_mock.mock()
    def test_import_local_bundle(self, m):
        """Asserts local bundles are first searched locally."""
        tmp_dir = tempfile.mkdtemp()
        bundle_file = os.path.join(tmp_dir, 'bundle.bundle')
        with open(os.path.join(tmp_dir, 'bundle.bundle'), 'w') as f:

            bundle_contents = {'Packages': [
                {'Name': 'first_app'},
                {'Name': 'second_app', 'Version': '1.0'}
            ]}
            json.dump(bundle_contents, f)

        pkg1 = make_pkg({'FullName': 'first_app',
                         'Require': {'third_app': None}})
        pkg2 = make_pkg({'FullName': 'second_app'})
        pkg3 = make_pkg({'FullName': 'third_app'})
        with open(os.path.join(tmp_dir, 'first_app'), 'w') as f:
            f.write(pkg1.read())
        with open(os.path.join(tmp_dir, 'third_app'), 'w') as f:
            f.write(pkg3.read())

        m.get(TestArgs.murano_repo_url + '/apps/first_app.zip',
              status_code=404)
        m.get(TestArgs.murano_repo_url + '/apps/second_app.1.0.zip',
              body=pkg2)
        m.get(TestArgs.murano_repo_url + '/apps/third_app.zip',
              status_code=404)

        args = TestArgs()
        args.filename = bundle_file
        v1_shell.do_bundle_import(self.client, args)

        self.client.packages.create.assert_has_calls(
            [
                mock.call({'is_public': False}, {'first_app': mock.ANY}),
                mock.call({'is_public': False}, {'second_app': mock.ANY}),
                mock.call({'is_public': False}, {'third_app': mock.ANY}),
            ], any_order=True,
        )
        shutil.rmtree(tmp_dir)
