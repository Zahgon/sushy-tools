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

import re

import fastapi

from sushy_tools.emulator import api_utils
from sushy_tools import error


certificate_service = fastapi.APIRouter(
    prefix='/redfish/v1/CertificateService',
    route_class=api_utils.RedfishRoute)


_VMEDIA_URI_PATTERN = re.compile(
    '/redfish/v1/Managers/([^/]+)/VirtualMedia/([^/]+)/Certificates/([^/]+)/?$'
)


@certificate_service.api_route('', methods=['GET'])
@api_utils.returns_json
def certificate_service_resource(request: fastapi.Request):
    api_utils.debug('Serving certificate service')
    return request.app.render_template('certificate_service.json')


@certificate_service.api_route('/CertificateLocations', methods=['GET'])
@api_utils.returns_json
def certificate_service_locations(request: fastapi.Request):
    api_utils.debug('Serving certificate locations')
    locations = []
    for mgr in request.app.managers.managers:
        for dev in request.app.vmedia.devices:
            try:
                certs = request.app.vmedia.list_certificates(mgr, dev)
            except error.NotFound:
                api_utils.debug('No certificates for manager %s, virtual '
                                'media device %s', mgr, dev)
                continue

            for cert in certs:
                locations.append(
                    f'/redfish/v1/Managers/{mgr}/VirtualMedia/{dev}'
                    f'/Certificates/{cert.id}'
                )

    return request.app.render_template('certificate_locations.json',
                                       certificates=locations)


@certificate_service.api_route(
    '/Actions/CertificateService.ReplaceCertificate', methods=['POST'],
    dependencies=[fastapi.Depends(api_utils.ensure_instance_access)])
@api_utils.returns_json
def certificate_service_replace_certificate(
        request: fastapi.Request,
        body=fastapi.Depends(api_utils.json_body)):
    if not body.json:
        raise error.BadRequest("Empty or malformed certificate")

    try:
        cert_string = body.json['CertificateString']
        cert_type = body.json['CertificateType']
        cert_uri = body.json['CertificateUri']
    except KeyError as exc:
        raise error.BadRequest(f"Missing required parameter {exc}")

    match = _VMEDIA_URI_PATTERN.search(cert_uri)
    if not match:
        raise error.NotFound(
            f"Certificates at URI {cert_uri} are not supported")

    if cert_type != 'PEM':
        raise error.BadRequest(
            f"Only PEM certificates are supported, got {cert_type}")

    manager_id, device, cert_id = match.groups()

    request.app.managers.get_manager(manager_id)
    request.app.vmedia.replace_certificate(
        manager_id, device, cert_id, cert_string, cert_type)

    return '', 204
