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

import functools
import html
import json
import logging
import re

import fastapi
from fastapi import responses
from fastapi import routing
from starlette import routing as starlette_routing

from sushy_tools import error as sushy_error

# The application's logger, which these helpers have always logged through
LOG = logging.getLogger('sushy_tools.emulator.main')


def debug(*args, **kwargs):
    LOG.debug(*args, **kwargs)


def info(*args, **kwargs):
    LOG.info(*args, **kwargs)


def warning(*args, **kwargs):
    LOG.warning(*args, **kwargs)


def error(*args, **kwargs):
    LOG.error(*args, **kwargs)


def instance_denied(config, **kwargs):
    deny = True

    try:
        deny = (kwargs['identity'] not in
                config['SUSHY_EMULATOR_ALLOWED_INSTANCES'])

    except KeyError:
        deny = False

    finally:
        if deny:
            warning('Instance %s access denied', kwargs.get('identity'))

        return deny


# The page the Flask release sends along with the Location header. Clients
# receive it as the redirect's body, and RedirectResponse has an empty one.
_REDIRECT_PAGE = (
    '<!doctype html>\n'
    '<html lang=en>\n'
    '<title>Redirecting...</title>\n'
    '<h1>Redirecting...</h1>\n'
    '<p>You should be redirected automatically to the target URL: '
    '<a href="{url}">{url}</a>. If not, click the link.\n'
)
_REPEATED_SLASHES = re.compile('/{2,}')


def redirect(url, code):
    return responses.HTMLResponse(
        _REDIRECT_PAGE.format(url=html.escape(url)), status_code=code,
        headers={'Location': url})


def ensure_instance_access(request: fastapi.Request):
    if instance_denied(request.app.config, **request.path_params):
        # The statement of the Flask release, kept for its answer. error is
        # the logging helper above in both releases, so this AttributeError
        # reaches all_exception_handler and a denied instance gets the same
        # 500 document as before, not a 404 that clients never received.
        raise error.NotFound()


# The decorator of the Flask release; only the response class is different.
def returns_json(decorated_func):
    @functools.wraps(decorated_func)
    def decorator(*args, **kwargs):
        response = decorated_func(*args, **kwargs)
        if isinstance(response, responses.Response):
            return response
        if isinstance(response, tuple):
            contents, status, *headers = response
        else:
            contents, status, headers = response, 200, ()
        kwargs = {'headers': headers[0]} if headers else {}
        return responses.Response(content=contents, status_code=status,
                                  media_type='application/json', **kwargs)

    return decorator


class JsonBody(object):
    """Request body decoded on first access, like Flask's request.json

    A route that never reads it accepts any body. One that does answers 415
    unless the body is declared as JSON and 400 unless it parses. FastAPI's
    body parameters cannot express this: they are parsed before the handler
    runs, whether or not it reads them, and failures answer 422.
    """

    def __init__(self, data, content_type):
        self._data = data
        self._mimetype = content_type.split(';')[0].strip().lower()

    @functools.cached_property
    def json(self):
        if not (self._mimetype == 'application/json'
                or (self._mimetype.startswith('application/')
                    and self._mimetype.endswith('+json'))):
            raise sushy_error.UnsupportedMediaType()
        try:
            return json.loads(self._data)
        except ValueError as exc:
            raise sushy_error.InvalidJSONBody() from exc


async def json_body(request: fastapi.Request):
    return JsonBody(await request.body(),
                    request.headers.get('content-type', ''))


def allowed_methods(request):
    """The methods the application's routes answer for this request's URL"""
    return [method for method in ('DELETE', 'GET', 'HEAD', 'OPTIONS', 'PATCH',
                                  'POST', 'PUT')
            if any(route.matches({**request.scope, 'method': method})[0]
                   is starlette_routing.Match.FULL
                   for route in request.app.routes)]


class RedfishRoute(routing.APIRoute):
    """Route answering like a Flask rule with strict_slashes turned off

    FastAPI has no such option: redirect_slashes either answers 307 or leaves
    the other form 404. So this plugs into FastAPI's route_class hook, and the
    path matching itself stays APIRoute.matches, asked about each path form.
    Both trailing slash forms are served directly, never through a redirect,
    and repeated slashes get the 308 to the merged URL. A rule answers OPTIONS
    with the methods of its URL and, when it serves GET, also answers HEAD,
    neither of which APIRoute adds by itself.
    Every exception raised by a handler or its dependencies goes to the
    application's Exception handler, which renders error.json, so FastAPI's
    {"detail": ...} and 422 documents are not produced.
    """

    def __init__(self, path, endpoint, *, methods=None, **kwargs):
        methods = set(methods or ())
        if 'GET' in methods:
            methods.add('HEAD')
        super().__init__(path, endpoint, methods=methods | {'OPTIONS'},
                         **kwargs)

    def matches(self, scope):
        path = scope.get('path')
        merged = path and _REPEATED_SLASHES.sub('/', path)
        if merged != path:
            match, child_scope = self.matches({**scope, 'path': merged})
            return match, {**child_scope, 'merged_path': merged}
        match, child_scope = super().matches(scope)
        if match is not starlette_routing.Match.NONE or path in (None, '/'):
            return match, child_scope
        if path.endswith('/'):
            return super().matches({**scope, 'path': path[:-1]})
        # A path missing the trailing slash of its route is only served
        # when the method matches too; otherwise it is not found.
        match, child_scope = super().matches({**scope, 'path': path + '/'})
        if match is starlette_routing.Match.FULL:
            return match, child_scope
        return starlette_routing.Match.NONE, {}

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def redfish_route_handler(request):
            merged_path = request.scope.get('merged_path')
            if merged_path:
                return redirect(str(request.url.replace(path=merged_path)),
                                308)
            if request.method == 'OPTIONS':
                return responses.HTMLResponse(
                    headers={'Allow': ', '.join(allowed_methods(request))})
            try:
                return await handler(request)
            except Exception as exc:
                return request.app.exception_handlers[Exception](
                    request, exc)

        return redfish_route_handler
