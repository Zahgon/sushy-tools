# Copyright 2018 Red Hat, Inc.
# All Rights Reserved.
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


import http


class FishyError(Exception):
    """Create generic sushy-tools exception object"""

    def __init__(self, msg='Unknown error', code=500):
        super().__init__(msg)
        self.code = code


class AliasAccessError(FishyError):
    """Node access attempted via an alias, not UUID"""


class NotSupportedError(FishyError):
    """Feature not supported by resource driver"""

    def __init__(self, msg='Unsupported', code=501):
        super().__init__(msg, code)


class NotFound(FishyError):
    """Entity not found."""

    def __init__(self, msg='Not found', code=404):
        super().__init__(msg, code)


class BadRequest(FishyError):
    """Malformed request."""

    def __init__(self, msg, code=400):
        super().__init__(msg, code)


class FeatureNotAvailable(NotFound):
    """Feature is not available."""

    def __init__(self, feature, code=404):
        super().__init__(f"Feature {feature} not available", code=code)


class Conflict(FishyError):
    """Conflict with current state of the resource."""

    def __init__(self, msg, code=409):
        super().__init__(msg, code)


class ConfigInvalid(FishyError):
    """Config is invalid."""

    def __init__(self, msg, code=500):
        errmsg = f"Invalid configuration file. {msg}"
        super().__init__(errmsg, code)


class Unauthorized(FishyError):
    """Unauthorized for resource"""

    def __init__(self, msg, code=401):
        self.headers = {'WWW-Authenticate': 'Basic realm="Baremetal API"'}
        super().__init__(msg, code)


class InvalidJSONBody(FishyError):
    """Request body is not valid JSON."""

    def __init__(self, code=400):
        super().__init__('400 Bad Request: The browser (or proxy) sent a '
                         'request that this server could not understand.',
                         code)


class UnsupportedMediaType(FishyError):
    """Request body read as JSON is not declared as JSON."""

    def __init__(self, code=415):
        super().__init__('415 Unsupported Media Type: Did not attempt to load '
                         'JSON data because the request Content-Type was not '
                         "'application/json'.", code)


class HTTPError(FishyError):
    """HTTP error reported with its status line and description."""

    _DESCRIPTIONS = {
        404: ('The requested URL was not found on the server. If you entered '
              'the URL manually please check your spelling and try again.'),
        405: 'The method is not allowed for the requested URL.',
        500: ('The server encountered an internal error and was unable to '
              'complete your request. Either the server is overloaded or '
              'there is an error in the application.'),
    }

    def __init__(self, code):
        phrase = http.HTTPStatus(code).phrase
        description = self._DESCRIPTIONS.get(code, '')
        super().__init__(f'{code} {phrase}: {description}', code)
