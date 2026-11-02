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

from unittest import mock

from fastapi import exceptions as fastapi_exc
from fastapi import routing
from starlette import exceptions as starlette_exc

from sushy_tools.emulator.controllers import certificate_service as certctl
from sushy_tools.emulator.controllers import update_service as usctl
from sushy_tools.emulator.controllers import virtual_media as vmctl
from sushy_tools.emulator import main
from sushy_tools import error
from sushy_tools.tests.unit.emulator import test_main


NOT_FOUND = ('404 Not Found: The requested URL was not found on the server. '
             'If you entered the URL manually please check your spelling and '
             'try again.')
NOT_ALLOWED = ('405 Method Not Allowed: The method is not allowed for the '
               'requested URL.')
BAD_JSON = ('400 Bad Request: The browser (or proxy) sent a request that this '
            'server could not understand.')
NOT_JSON = ("415 Unsupported Media Type: Did not attempt to load JSON data "
            "because the request Content-Type was not 'application/json'.")


class WireContractTestCase(test_main.EmulatorTestCase):
    """The responses of the Flask release that FastAPI would answer otherwise

    Each test names the FastAPI default it keeps off the wire.
    """

    def assertErrorDocument(self, response, status_code, message):
        self.assertEqual(status_code, response.status_code)
        self.assertEqual('application/json',
                         response.headers['content-type'])
        self.assertNotIn('detail', response.json())
        self.assertEqual(message, response.json()['error']['message'])
        self.assertEqual('Base.1.0.GeneralError',
                         response.json()['error']['code'])

    def test_unknown_url_is_not_a_detail_document(self):
        response = self.app.get('/redfish/v1/nope')

        self.assertErrorDocument(response, 404, NOT_FOUND)

    def test_unsupported_method_is_not_a_detail_document(self):
        response = self.app.delete('/redfish/v1/Chassis')

        self.assertErrorDocument(response, 405, NOT_ALLOWED)

    def test_unsupported_method_has_no_allow_header(self):
        # The Flask error handler built a new response, without Werkzeug's.
        response = self.app.delete('/redfish/v1/Chassis')

        self.assertEqual(405, response.status_code)
        self.assertNotIn('allow', response.headers)

    @mock.patch.dict(main.app.config,
                     {'SUSHY_EMULATOR_ALLOWED_INSTANCES': {'allowed'}})
    def test_denied_instance_keeps_the_500_of_the_flask_release(self):
        # ensure_instance_access has always hit the error logging helper.
        response = self.app.get('/redfish/v1/Systems/denied')

        self.assertErrorDocument(
            response, 500, "'function' object has no attribute 'NotFound'")

    def test_routes_declare_nothing_fastapi_would_validate(self):
        for routes in (main.app.routes, certctl.certificate_service.routes,
                       vmctl.virtual_media.routes,
                       usctl.update_service.routes):
            for route in routes:
                if isinstance(route, routing.APIRoute):
                    dependant = route.dependant
                    self.assertEqual(
                        [], dependant.body_params + dependant.query_params
                        + dependant.header_params + dependant.cookie_params,
                        route.path)

    def test_trailing_slash_forms_do_not_redirect(self):
        for url in ('/redfish/v1', '/redfish/v1/',
                    '/redfish/v1/CertificateService',
                    '/redfish/v1/CertificateService/',
                    '/redfish/v1/UpdateService',
                    '/redfish/v1/UpdateService/'):
            response = self.app.get(url)

            self.assertEqual(200, response.status_code, url)
            self.assertNotIn('location', response.headers)

    def test_missing_slash_with_wrong_method_is_not_found(self):
        response = self.app.post('/redfish/v1')

        self.assertErrorDocument(response, 404, NOT_FOUND)

    @test_main.patch_resource('chassis')
    def test_invalid_json_body_is_not_a_validation_error(self, chassis_mock):
        response = self.app.patch(
            '/redfish/v1/Chassis/xxxx-yyyy-zzzz', content='not-json',
            headers={'Content-Type': 'application/json'})

        self.assertErrorDocument(response, 400, BAD_JSON)

    @test_main.patch_resource('chassis')
    def test_undeclared_json_body_is_not_a_validation_error(self,
                                                            chassis_mock):
        response = self.app.patch(
            '/redfish/v1/Chassis/xxxx-yyyy-zzzz', content='{}',
            headers={'Content-Type': 'text/plain'})

        self.assertErrorDocument(response, 415, NOT_JSON)

    @test_main.patch_resource('chassis')
    def test_missing_body_is_not_a_validation_error(self, chassis_mock):
        response = self.app.patch('/redfish/v1/Chassis/xxxx-yyyy-zzzz')

        self.assertErrorDocument(response, 415, NOT_JSON)

    @test_main.patch_resource('chassis')
    def test_alias_redirects_with_flask_page(self, chassis_mock):
        chassis_mock.return_value.uuid.side_effect = (
            error.AliasAccessError('real-uuid'))

        response = self.app.get('/redfish/v1/Chassis/alias')

        self.assertEqual(307, response.status_code)
        self.assertEqual('/redfish/v1/Chassis/real-uuid',
                         response.headers['location'])
        self.assertEqual('text/html; charset=utf-8',
                         response.headers['content-type'])
        self.assertIn(b'<title>Redirecting...</title>', response.content)

    def test_generated_documentation_routes_do_not_exist(self):
        for url in ('/docs', '/redoc', '/openapi.json'):
            self.assertErrorDocument(self.app.get(url), 404, NOT_FOUND)

    def test_exception_handlers_render_error_document(self):
        for exc_class in (starlette_exc.HTTPException,
                          fastapi_exc.RequestValidationError, Exception):
            self.assertIs(main.all_exception_handler,
                          main.app.exception_handlers[exc_class])

    def test_get_route_answers_head_without_a_body(self):
        response = self.app.head('/redfish/v1/')

        self.assertEqual(200, response.status_code)
        self.assertEqual(b'', response.content)

    def test_options_lists_the_methods_of_the_url(self):
        response = self.app.options('/redfish/v1/Chassis/xxxx-yyyy-zzzz')

        self.assertEqual(200, response.status_code)
        self.assertEqual(b'', response.content)
        self.assertEqual('GET, HEAD, OPTIONS, PATCH',
                         response.headers['allow'])

    def test_repeated_slashes_redirect_to_the_merged_url(self):
        response = self.app.get('/redfish//v1/Registries')

        self.assertEqual(308, response.status_code)
        self.assertEqual('http://testserver/redfish/v1/Registries',
                         response.headers['location'])

    def test_repeated_slashes_with_wrong_method_are_not_allowed(self):
        response = self.app.delete('/redfish//v1/Registries')

        self.assertErrorDocument(response, 405, NOT_ALLOWED)
