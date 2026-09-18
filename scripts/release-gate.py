#!/usr/bin/env python3
"""Exercise the exact release image on the dedicated builder before publication."""
import base64
import hashlib
import http.server
import http.cookiejar
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import xmlrpc.client

spec = importlib.util.spec_from_file_location('registry_check', Path(__file__).with_name('registry-check.py'))
registry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registry)
if len(sys.argv) != 2 or sys.argv[1] != registry.EXPECTED:
    raise SystemExit('Usage: release-gate.py ' + registry.EXPECTED)
image = sys.argv[1]
run_id = 'flood-release-gate-' + uuid.uuid4().hex[:12]
work = Path(tempfile.mkdtemp(prefix=run_id + '-'))
containers = []
volumes = []
password = secrets.token_urlsafe(24)
user = 'releasegate'
callback_token = secrets.token_urlsafe(24)
callbacks = []
openers = {}
auth = 'Basic ' + base64.b64encode((user + ':' + password).encode()).decode()


def command(args, data=None, timeout=180):
    p = subprocess.run(args, input=data, capture_output=True, timeout=timeout)
    if p.returncode:
        # Do not print command arguments, container environment or unredacted logs.
        diagnostic = p.stderr.decode(errors='replace')[-1200:]
        for secret in (password, callback_token, auth):
            diagnostic = diagnostic.replace(secret, '[redacted]')
        raise RuntimeError('Builder command failed: ' + diagnostic)
    return p.stdout


class Callback(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/v1/apps/installed/900000082':
            callbacks.append(self.headers.get('X-Cylo-Callback-Token'))
            self.send_response(200)
        else:
            self.send_response(404)
        self.end_headers()
    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(('0.0.0.0', 0), Callback)
threading.Thread(target=server.serve_forever, daemon=True).start()


def storage(suffix):
    result = []
    for part in ('torrents', 'database'):
        name = run_id + '-' + suffix + '-' + part
        command(['docker', 'volume', 'create', '--label', 'appbox.release-gate=' + run_id, name])
        volumes.append(name)
        result.append(name)
    return result


def launch(suffix, selected_image, mounts, baseline=False):
    name = run_id + '-' + suffix
    args = ['docker', 'create', '--platform', 'linux/amd64', '--name', name,
            '--label', 'appbox.release-gate=' + run_id, '--init',
            '--add-host', 'host.docker.internal:host-gateway', '-p', '127.0.0.1::80',
            '-v', mounts[0] + ':/torrents', '-v', mounts[1] + ':/home/flood/.local',
            '-e', 'USERNAME=' + user, '-e', 'PASSWORD=' + password,
            '-e', 'LISTENING_PORT=49160', '-e', 'DHT_PORT=49161',
            '-e', 'INSTANCE_ID=900000082', '-e', 'CALLBACK_TOKEN=' + callback_token,
            '-e', 'APPBOX_API_URL=http://host.docker.internal:' + str(server.server_port) + '/v1']
    if baseline:
        args += ['--entrypoint', '/bin/bash', selected_image, '/tmp/gate-start.sh']
    else:
        args += [selected_image]
    command(args)
    containers.append(name)
    if baseline:
        script = work / 'baseline-start.sh'
        command(['docker', 'cp', name + ':/scripts/start.sh', str(script)])
        source = script.read_text().replace('set -x', 'set +x')
        # Only redirect the callback of this disposable fixture to our local stub.
        for domain in ('api.cylo.io', 'api.cylo.net'):
            source = source.replace('https://' + domain + '/v1/apps/installed/',
                                    'http://host.docker.internal:' + str(server.server_port) + '/v1/apps/installed/')
        script.write_text(source)
        command(['docker', 'cp', str(script), name + ':/tmp/gate-start.sh'])
    command(['docker', 'start', name])
    return name


def url(name, path):
    binding = command(['docker', 'port', name, '80/tcp']).decode().strip()
    return 'http://' + binding + path


def request(name, path, data=None, authenticated=True):
    headers = {'Authorization': auth} if authenticated else {}
    if data is not None:
        headers['Content-Type'] = 'application/json' if path.startswith('/api/') else 'text/xml'
    if name not in openers:
        openers[name] = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    with openers[name].open(urllib.request.Request(url(name, path), data=data, headers=headers), timeout=10) as response:
        return response.status, response.read()


def rpc(name, method, *params):
    _, body = request(name, '/RPC2', xmlrpc.client.dumps(params, methodname=method).encode())
    return xmlrpc.client.loads(body)[0][0]


def wait_ready(name, expected):
    last_error = ''
    for attempt in range(90):
        try:
            assert request(name, '/')[0] == 200
            version = rpc(name, 'system.client_version')
            if expected:
                assert version == expected, version
            return
        except Exception as error:
            last_error = type(error).__name__
            time.sleep(2)
    # Logs are from disposable synthetic-data fixtures only; redact credentials.
    logs = command(['docker', 'logs', '--tail', '60', name]).decode(errors='replace')
    for secret in (password, callback_token, auth):
        logs = logs.replace(secret, '[redacted]')
    logs = re.sub(r'(?im)^.*(?:password|authorization|callback_token).*$','[authentication detail omitted]',logs)
    print(logs[-6000:], flush=True)
    raise RuntimeError('Readiness failed: ' + last_error)


def check_web(name):
    try:
        request(name, '/', authenticated=False)
        raise AssertionError('Unauthenticated request succeeded')
    except urllib.error.HTTPError as error:
        assert error.code == 401
    _, html = request(name, '/')
    assets = re.findall(rb'(?:src|href)="([^" ]+\.(?:js|css))"', html)
    assert assets, 'No frontend assets'
    for asset in assets[:4]:
        path = asset.decode()
        if path.startswith('/'):
            assert len(request(name, path)[1]) > 100
    assert request(name, '/api/auth/authenticate', json.dumps({'username': user, 'password': password}).encode())[0] == 200
    assert request(name, '/api/torrents')[0] == 200


def bencode(value):
    if isinstance(value, int):
        return b'i' + str(value).encode() + b'e'
    if isinstance(value, bytes):
        return str(len(value)).encode() + b':' + value
    if isinstance(value, dict):
        return b'd' + b''.join(bencode(k) + bencode(v) for k, v in sorted(value.items())) + b'e'
    raise TypeError()


def seed(name):
    payload = b'Appbox Flood release persistence fixture\n' * 100
    info = {b'name': b'flood-gate.bin', b'length': len(payload), b'piece length': 16384,
            b'pieces': hashlib.sha1(payload).digest(), b'private': 1}
    torrent = {b'announce': b'http://127.0.0.1:9/announce', b'info': info}
    (work / 'flood-gate.bin').write_bytes(payload)
    (work / 'fixture.torrent').write_bytes(bencode(torrent))
    command(['docker', 'cp', str(work / 'flood-gate.bin'), name + ':/torrents/downloading/flood-gate.bin'])
    command(['docker', 'cp', str(work / 'fixture.torrent'), name + ':/tmp/fixture.torrent'])
    rpc(name, 'load.normal', '', '/tmp/fixture.torrent')
    torrent_hash = hashlib.sha1(bencode(info)).hexdigest().upper()
    for _ in range(20):
        if torrent_hash in rpc(name, 'download_list'):
            break
        time.sleep(1)
    assert torrent_hash in rpc(name, 'download_list')
    rpc(name, 'd.custom1.set', torrent_hash, 'release-preserved')
    rpc(name, 'session.save')
    command(['docker', 'exec', name, 'sh', '-c', "printf '\n# release-gate preserved configuration\n' >> /torrents/config/rtorrent/.rtorrent.rc"])
    return torrent_hash, hashlib.sha256(payload).hexdigest()


def check_persisted(name, fixture):
    torrent_hash, digest = fixture
    assert torrent_hash in rpc(name, 'download_list')
    assert rpc(name, 'd.custom1', torrent_hash) == 'release-preserved'
    actual = command(['docker', 'exec', name, 'sha256sum', '/torrents/downloading/flood-gate.bin']).decode().split()[0]
    assert actual == digest
    config = command(['docker', 'exec', name, 'cat', '/torrents/config/rtorrent/.rtorrent.rc'])
    assert b'# release-gate preserved configuration' in config
    check_web(name)


try:
    details = json.loads(command(['docker', 'image', 'inspect', image]))[0]
    assert details['Architecture'] == 'amd64' and details['Os'] == 'linux'
    version = command(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'flood', image, '--version']).decode()
    assert '4.16.1' in version
    fresh = launch('fresh', image, storage('fresh'))
    wait_ready(fresh, '0.16.23')
    check_web(fresh)
    assert rpc(fresh, 'dht.port') == 49161
    assert rpc(fresh, 'network.port_range') == '49160-49160'
    for _ in range(30):
        if callback_token in callbacks:
            break
        time.sleep(1)
    assert callback_token in callbacks, 'Authenticated install callback missing'
    fixture = seed(fresh)
    print('PASS fresh: versions, HTTP/assets, authentication, RPC, ports, callback and torrent session', flush=True)
    command(['docker', 'restart', '--time', '45', fresh])
    wait_ready(fresh, '0.16.23')
    check_persisted(fresh, fixture)
    print('PASS restart: data, torrent state, settings and authentication preserved', flush=True)
    upgrade_storage = storage('upgrade')
    baseline = launch('baseline', registry.PREVIOUS, upgrade_storage, baseline=True)
    wait_ready(baseline, None)
    baseline_fixture = seed(baseline)
    command(['docker', 'stop', '--time', '45', baseline])
    upgraded = launch('upgraded', image, upgrade_storage)
    wait_ready(upgraded, '0.16.23')
    check_persisted(upgraded, baseline_fixture)
    print('PASS upgrade: current catalog image data, session, settings and authentication preserved', flush=True)
finally:
    for name in reversed(containers):
        try:
            label = command(['docker', 'inspect', '--format', '{{index .Config.Labels "appbox.release-gate"}}', name]).decode().strip()
            if label != run_id:
                raise RuntimeError('Container cleanup identity mismatch')
            command(['docker', 'rm', '-f', name])
        except Exception as error:
            print('Cleanup requires attention:', name, type(error).__name__, flush=True)
    for name in volumes:
        try:
            label = command(['docker', 'volume', 'inspect', '--format', '{{index .Labels "appbox.release-gate"}}', name]).decode().strip()
            if label != run_id:
                raise RuntimeError('Volume cleanup identity mismatch')
            command(['docker', 'volume', 'rm', name])
        except Exception as error:
            print('Cleanup requires attention:', name, type(error).__name__, flush=True)
    server.shutdown()
    if work.parent == Path(tempfile.gettempdir()) and work.name.startswith(run_id + '-'):
        shutil.rmtree(work)

registry.require_absent(image)
print('PASS all release gates', flush=True)
