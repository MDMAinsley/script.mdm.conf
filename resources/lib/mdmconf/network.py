"""Read-only DNS and provider checks from the device running Kodi."""
from http.client import HTTPSConnection, HTTPException
import ipaddress
import json
from queue import Empty, Queue
import socket
import ssl
from threading import Lock, Thread
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

HOST = 'torrentio.strem.fun'
PATH = '/stream/series/tt0386676:4:10.json'
DOH = 'https://1.1.1.1/dns-query?name=' + HOST + '&type=A'
HEADERS = {'User-Agent':'MDM-Link/0.1.0', 'Accept':'application/json'}
LIMIT = 4 * 1024 * 1024
TIMEOUT = 4
_guard = Lock()
_workers = []


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ProviderAddressConnection(HTTPSConnection):
    """Connect to a diagnostic IP while verifying TLS for the real hostname."""
    def __init__(self, address):
        self.address = str(address)
        self.tls = ssl.create_default_context()
        super().__init__(HOST, 443, timeout=TIMEOUT, context=self.tls)

    def connect(self):
        raw = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self.tls.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def read_json(response, limit):
    body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError('Response too large')
    payload = json.loads(body.decode('utf8'))
    if not isinstance(payload, dict):
        raise ValueError('Response is not a JSON object')
    return payload


def device_dns():
    answers = socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)
    addresses = {ipaddress.ip_address(row[4][0]) for row in answers}
    if not addresses:
        return {'status':'No addresses'}
    return {'status':'Resolved', 'addresses':addresses}


def cloudflare_dns():
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request(DOH, headers={'Accept':'application/dns-json'})
    with opener.open(request, timeout=TIMEOUT) as response:
        data = read_json(response, 65536)
    if type(data.get('Status')) is not int or not 0 <= data['Status'] <= 15:
        raise ValueError('Invalid DNS response')
    if data['Status'] != 0:
        return {'status':'DNS response code {}'.format(data['Status'])}
    answers = data.get('Answer', [])
    if not isinstance(answers, list):
        raise ValueError('Invalid DNS answer')
    addresses = set()
    for answer in answers:
        if isinstance(answer, dict) and answer.get('type') == 1:
            try:
                address = ipaddress.IPv4Address(answer.get('data'))
            except (ValueError, TypeError):
                continue
            if address.is_global and not address.is_multicast:
                addresses.add(address)
    if not addresses:
        return {'status':'No public IPv4 addresses'}
    return {'status':'Resolved', 'addresses':addresses}


def provider_https(address=None):
    if address is None:
        opener = build_opener(NoRedirect())
        request = Request('https://' + HOST + PATH, headers=HEADERS)
        with opener.open(request, timeout=TIMEOUT) as response:
            data = read_json(response, LIMIT)
    else:
        connection = ProviderAddressConnection(address)
        try:
            connection.request('GET', PATH, headers=HEADERS)
            with connection.getresponse() as response:
                if response.status != 200:
                    return {'status':'HTTP {}'.format(response.status)}
                data = read_json(response, LIMIT)
        finally:
            connection.close()
    if not isinstance(data.get('streams'), list):
        raise ValueError('Invalid provider result')
    return {'status':'OK', 'sources':len(data['streams'])}


def probe(task):
    started = time.monotonic()
    try:
        result = task()
    except HTTPError as error:
        error.close()
        result = {'status':'HTTP {}'.format(error.code)}
    except (OSError, HTTPException) as error:
        cause = error.reason if isinstance(error, URLError) else error
        if isinstance(cause, socket.gaierror):
            status = 'DNS lookup failed'
        elif isinstance(cause, ssl.SSLCertVerificationError):
            status = 'TLS certificate rejected'
        elif isinstance(cause, ssl.SSLError):
            status = 'TLS handshake failed'
        elif isinstance(cause, TimeoutError):
            status = 'Timed out'
        else:
            status = 'Connection failed'
        result = {'status':status}
    except (ValueError, RecursionError):
        result = {'status':'Invalid response'}
    return dict(result, seconds=round(time.monotonic()-started, 2))


def check(cancel=lambda:False, seconds=10):
    """Run independent probes without waiting indefinitely for a DNS worker."""
    if not _guard.acquire(blocking=False):
        return {'busy':True}
    try:
        _workers[:] = [worker for worker in _workers if worker.is_alive()]
        if _workers:
            return {'busy':True}
        queue = Queue()
        pending = set()
        results = {}
        if cancel():
            return None
        started = time.monotonic()
        deadline = started + seconds

        def start(name, task):
            pending.add(name)
            worker = Thread(target=lambda:queue.put((name, probe(task))), daemon=True)
            worker.start()
            _workers.append(worker)

        start('device_dns', device_dns)
        start('device_https', provider_https)
        start('cloudflare', cloudflare_dns)
        alternate_started = False
        while pending and time.monotonic() < deadline:
            if cancel():
                return None
            try:
                name, result = queue.get(timeout=min(0.1, max(0, deadline-time.monotonic())))
            except Empty:
                pass
            else:
                pending.remove(name)
                results[name] = result
            direct = results.get('device_https', {}).get('status', '')
            alternate = results.get('cloudflare', {}).get('addresses', set())
            direct_unavailable = direct in ('DNS lookup failed','Timed out','Connection failed')
            direct_stalled = not direct and time.monotonic()-started >= 3.5
            if (not alternate_started and alternate
                    and (direct_unavailable or direct_stalled)
                    and deadline-time.monotonic() >= 1):
                address = min(alternate)
                start('alternate_https', lambda:provider_https(address))
                alternate_started = True
        if cancel():
            return None
        for name in pending:
            results[name] = {'status':'Check deadline reached'}
        return results
    finally:
        _guard.release()


def report(results):
    if results.get('busy'):
        return 'A previous network check is still finishing. Try again in a moment.'
    labels = [('device_dns','Device DNS'), ('device_https','Torrentio HTTPS'),
              ('cloudflare','Cloudflare comparison'), ('alternate_https','HTTPS using a Cloudflare IPv4 answer')]
    lines = []
    for key, label in labels:
        if key not in results:
            continue
        row = results[key]
        detail = row['status']
        if 'addresses' in row:
            ipv4 = sum(a.version == 4 for a in row['addresses'])
            detail += ' ({} IPv4, {} IPv6)'.format(ipv4, len(row['addresses'])-ipv4)
        if 'sources' in row:
            detail += ' ({} source listings)'.format(row['sources'])
        if 'seconds' in row:
            detail += ' · {:.2f}s'.format(row['seconds'])
        lines.append(label+' — '+detail)
    lines.append('')
    device = results.get('device_dns', {})
    direct = results.get('device_https', {}).get('status')
    alternate = results.get('alternate_https', {}).get('status')
    if direct == 'OK':
        lines.append('The device reached Torrentio. Keep the current DNS settings.')
    elif alternate == 'OK' and not device.get('addresses'):
        lines.append('The alternate address worked while the device DNS lookup failed. Check the device or router DNS settings.')
    elif alternate == 'OK':
        lines.append('The alternate IPv4 connection worked. Check the device network route or DNS settings. This can also be an IPv4/IPv6 difference.')
    elif device.get('addresses'):
        lines.append('The device resolved the name. Check the HTTPS result before changing DNS. A configured Link backup feed can provide another route.')
    else:
        lines.append('The device DNS or network check failed. Check the device connection and router settings.')
    lines += ['', 'Device DNS shows lookup results. It does not identify the configured DNS server.',
              'This check uses one fixed metadata lookup and leaves device and addon settings unchanged.']
    return '\n'.join(lines)


def run():
    import xbmc
    import xbmcgui

    dialog = xbmcgui.Dialog()
    if not dialog.yesno('MDM Conf - Network check',
                        'Check this device’s DNS and Torrentio connection? The check sends a fixed hostname lookup to Cloudflare and requests one public source list.'):
        return
    monitor = xbmc.Monitor()
    progress = xbmcgui.DialogProgress()
    progress.create('MDM Conf - Network check', 'Checking the device connection and Cloudflare DNS…')
    try:
        result = check(lambda:progress.iscanceled() or monitor.abortRequested())
    finally:
        progress.close()
    if result is not None:
        dialog.textviewer('MDM Conf - Network check', report(result))
