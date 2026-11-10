"""Conf-only Google Drive storage and TV device authorization."""
from dataclasses import dataclass, field
import http.client
import json
import re
import ssl
import time
from urllib.parse import urlencode, urlsplit

from . import builds

OAUTH = 'oauth2.googleapis.com'
DRIVE = 'www.googleapis.com'
BROKER = 'mdmskip.mdmainsley.co.uk'
BROKER_PATH = '/conf-oauth/token'
VERIFICATION = 'https://www.google.com/device'
SCOPE = 'https://www.googleapis.com/auth/drive.file'
DEVICE_GRANT = 'urn:ietf:params:oauth:grant-type:device_code'
FILE_ID = re.compile(r'[A-Za-z0-9_-]{1,200}')
BUILD_TAG = {'mdm_conf': 'portable_build_v1'}


def config_file():
    return builds.profile() / 'google-tv-client.json'


def token_file():
    return builds.profile() / 'google-drive-login.json'


def read_json(path):
    try:
        with path.open('rb') as stream:
            raw = stream.read(8193)
        value = json.loads(raw) if len(raw) <= 8192 else None
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def visible_ascii(value, maximum=4096):
    return isinstance(value, str) and 0 < len(value) <= maximum and value.isascii() and value.isprintable()


def credential(value):
    return visible_ascii(value) and not any(ch.isspace() for ch in value)


def configuration():
    downloaded = read_json(config_file())
    client = downloaded.get('installed', downloaded)
    if isinstance(client, dict):
        identity = client.get('client_id')
        secret = client.get('client_secret')
        if (credential(identity) and identity.endswith('.apps.googleusercontent.com')
                and credential(secret)):
            return {'client_id': identity, 'client_secret': secret}
    try:
        from .google_tv_client import CLIENT_ID
    except ImportError:
        return None
    if credential(CLIENT_ID) and CLIENT_ID.endswith('.apps.googleusercontent.com'):
        return {'client_id': CLIENT_ID}
    return None


def saved_login(client):
    record = read_json(token_file())
    if record.get('client_id') == client['client_id'] and credential(record.get('refresh_token')):
        return record['refresh_token']
    return None


def ready():
    client = configuration()
    return bool(client and saved_login(client))


def request(host, method, path, *, body=None, headers=None, limit=2*1024*1024):
    # All host names are fixed. Redirects are returned to the caller and never
    # followed with authorization, a device code or a resumable upload URL.
    if host not in (OAUTH, DRIVE, BROKER):
        raise builds.BuildError('Unexpected Google endpoint.')
    connection = None
    try:
        connection = http.client.HTTPSConnection(host, timeout=8, context=ssl.create_default_context())
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        raw = response.read(limit+1)
        if len(raw) > limit:
            raise builds.BuildError('Google response exceeded the permitted size.')
        return response.status, response.getheader('Location'), raw
    except builds.BuildError:
        raise
    except (OSError, ValueError, http.client.HTTPException):
        raise builds.BuildError('Google could not be reached. Check the connection and try again.') from None
    finally:
        if connection:
            connection.close()


def object_response(raw):
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise builds.BuildError('Google returned an invalid response.') from None
    if not isinstance(value, dict):
        raise builds.BuildError('Google returned an invalid response.')
    return value


def oauth(endpoint, values):
    if endpoint == '/token' and 'client_secret' not in values:
        grant = values['grant_type']
        field = 'device_code' if grant == DEVICE_GRANT else 'refresh_token'
        status, _, raw = request(BROKER, 'POST', BROKER_PATH,
                                 body=builds.encode({field: values[field]}),
                                 headers={'Content-Type': 'application/json'}, limit=32768)
    else:
        status, _, raw = request(OAUTH, 'POST', endpoint, body=urlencode(values).encode('ascii'),
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'}, limit=32768)
    if status == 429:
        return status, {'error': 'slow_down'}
    return status, object_response(raw)


@dataclass(frozen=True)
class Approval:
    device_code: str = field(repr=False)
    code: str
    address: str
    interval: int
    deadline: float


def start(client):
    status, value = oauth('/device/code', {'client_id': client['client_id'], 'scope': SCOPE})
    if status != 200:
        raise builds.BuildError('Google declined to start sign-in. Check the MDM TV client configuration.')
    device, code = value.get('device_code'), value.get('user_code')
    address = value.get('verification_url') or value.get('verification_uri')
    expires, interval = value.get('expires_in'), value.get('interval', 5)
    if (not credential(device) or not visible_ascii(code, 32) or not visible_ascii(address, 256)
            or type(expires) is not int or expires < 1 or type(interval) is not int or interval < 1):
        raise builds.BuildError('Google returned incomplete sign-in instructions.')
    parsed = urlsplit(address)
    if parsed.scheme != 'https' or parsed.netloc not in ('www.google.com', 'google.com', 'accounts.google.com') or parsed.fragment:
        raise builds.BuildError('Google returned an unexpected sign-in address.')
    return Approval(device, code, address, interval, time.monotonic()+min(expires, 1800))


def poll(client, approval, wait):
    interval = approval.interval
    while True:
        remaining = approval.deadline-time.monotonic()
        if remaining <= interval:
            if remaining > 0 and wait(remaining):
                return None
            raise builds.BuildError('The sign-in code expired. Start again for a new code.')
        if wait(interval):
            return None
        if time.monotonic() >= approval.deadline:
            raise builds.BuildError('The sign-in code expired. Start again for a new code.')
        status, value = oauth('/token', dict(client, device_code=approval.device_code, grant_type=DEVICE_GRANT))
        if wait(0):
            return None
        if status == 200:
            refresh = value.get('refresh_token')
            if not credential(refresh) or SCOPE not in str(value.get('scope', '')).split():
                raise builds.BuildError('Google did not grant access to MDM build files.')
            return refresh
        error = value.get('error')
        if error == 'authorization_pending':
            continue
        if error == 'slow_down' or status == 429:
            interval += 5
            continue
        if error in ('access_denied', 'authorization_declined'):
            raise builds.BuildError('Google sign-in was declined.')
        if error in ('expired_token', 'invalid_grant'):
            raise builds.BuildError('The sign-in code expired. Start again for a new code.')
        raise builds.BuildError('Google sign-in could not complete. Try again.')


def save_login(client, refresh):
    builds.atomic(token_file(), builds.encode({'client_id': client['client_id'], 'refresh_token': refresh}))


class Client:
    def __init__(self, client, check, update):
        self.check = check
        self.update = update
        self.check()
        refresh = saved_login(client)
        if not refresh:
            raise builds.BuildError('Choose Connect Google Drive in Conf storage setup.')
        status, value = oauth('/token', dict(client, refresh_token=refresh, grant_type='refresh_token'))
        token = value.get('access_token')
        if status != 200 or not credential(token) or str(value.get('token_type', '')).lower() != 'bearer':
            raise builds.BuildError('Google Drive sign-in could not be refreshed. Reconnect it in Conf storage setup.')
        self.authorization = 'Bearer '+token
        self.deadline = time.monotonic()+180

    def tick(self):
        self.check()
        if time.monotonic() >= self.deadline:
            raise builds.BuildError('Google Drive transfer timed out.')

    def api(self, method, path, *, body=None, headers=None, limit=2*1024*1024):
        self.tick()
        status, location, raw = request(DRIVE, method, path, body=body, limit=limit,
                                        headers=dict(headers or {}, Authorization=self.authorization))
        self.tick()
        if not 200 <= status < 300:
            if status == 401:
                raise builds.BuildError('Google Drive sign-in expired. Reconnect it in Conf storage setup.')
            raise builds.BuildError(f'Google Drive could not complete the request (HTTP {status}).')
        return location, raw

    def ensure_folder(self):
        # There is no setup request before listing tagged files.
        self.tick()

    def files(self, name=None):
        query = "trashed = false and appProperties has { key='mdm_conf' and value='portable_build_v1' }"
        params = {'spaces': 'drive', 'pageSize': '100', 'fields': 'nextPageToken,files(id,name,size)'}
        if name is not None:
            if not builds.FILENAME.fullmatch(name):
                raise builds.BuildError('Invalid remote build filename.')
            query += f" and name = '{name}'"
        params['q'] = query
        result = {}
        for _ in range(20):
            _, raw = self.api('GET', '/drive/v3/files?'+urlencode(params))
            data = object_response(raw)
            items = data.get('files')
            if not isinstance(items, list):
                raise builds.BuildError('Google Drive returned an invalid build listing.')
            for item in items:
                if not isinstance(item, dict):
                    continue
                filename, identifier, size = (str(item.get(k, '')) for k in ('name','id','size'))
                if not builds.FILENAME.fullmatch(filename) or not FILE_ID.fullmatch(identifier):
                    continue
                if filename in result and result[filename][0] != identifier:
                    raise builds.BuildError('Two Google Drive files use the same build name.')
                result[filename] = identifier, size
            page = data.get('nextPageToken')
            if not page:
                return result
            if not credential(page) or page == params.get('pageToken'):
                break
            params['pageToken'] = page
        raise builds.BuildError('Google Drive build listing exceeded its limit.')

    def list(self):
        return sorted((name for name, (_, size) in self.files().items()
                       if re.fullmatch(r'[0-9]{1,8}', size) and 0 < int(size) <= builds.MAX_ARCHIVE),
                      reverse=True)

    def read_file(self, identifier):
        if not FILE_ID.fullmatch(identifier):
            raise builds.BuildError('Google Drive returned an invalid file identity.')
        _, raw = self.api('GET', f'/drive/v3/files/{identifier}?alt=media', limit=builds.MAX_ARCHIVE)
        return raw

    def upload(self, path):
        builds.read(path)
        raw = path.read_bytes()
        if len(raw) > builds.MAX_ARCHIVE or self.files(path.name):
            raise builds.BuildError('This build already exists in Google Drive or exceeds the size limit.')
        metadata = {'name': '.upload-'+path.name, 'mimeType': 'application/zip'}
        location, _ = self.api('POST', '/upload/drive/v3/files?uploadType=resumable&fields=id',
                               body=builds.encode(metadata),
                               headers={'Content-Type': 'application/json', 'X-Upload-Content-Type': 'application/zip',
                                        'X-Upload-Content-Length': str(len(raw))})
        url = urlsplit(location or '')
        if (url.scheme != 'https' or url.netloc != DRIVE or url.path != '/upload/drive/v3/files'
                or not url.query or url.fragment or not visible_ascii(location, 4096)):
            raise builds.BuildError('Google Drive returned an unexpected upload address.')
        self.update(25, 'Sending build to Google Drive')
        _, created = self.api('PUT', url.path+'?'+url.query, body=raw,
                              headers={'Content-Type': 'application/zip'})
        identifier = object_response(created).get('id')
        if not isinstance(identifier, str) or not FILE_ID.fullmatch(identifier):
            raise builds.BuildError('Google Drive did not return a valid upload identity.')
        self.update(65, 'Verifying uploaded build')
        if builds.digest(raw) != builds.digest(self.read_file(identifier)):
            raise builds.BuildError('Google Drive upload failed its integrity check.')
        if self.files(path.name):
            raise builds.BuildError('This build already exists in Google Drive.')
        self.api('PATCH', f'/drive/v3/files/{identifier}',
                 body=builds.encode({'name': path.name, 'appProperties': BUILD_TAG}),
                 headers={'Content-Type': 'application/json'})
        self.update(100, 'Build uploaded and verified')

    def download(self, name):
        from .cloud import cache_download
        match = self.files(name).get(name)
        if not match:
            raise builds.BuildError('This build is no longer available in Google Drive.')
        path = cache_download(name, self.read_file(match[0]), self.tick)
        self.update(100, 'Build downloaded and verified')
        return path


def configured(check, update):
    client = configuration()
    if not client:
        raise builds.BuildError('Google Drive setup requires an MDM TV client configuration.')
    return Client(client, check, update)
