#!/usr/bin/env python3
"""Exercise the exact release image, with the accepted session-race exception.

The operator authorized release on 2026-09-19 with rTorrent issue #2017 open.
Persistence fixtures wait for each save to commit and do not cover overlapping
saves; the separate regression test reproduces that known upstream defect.
"""
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
from urllib.parse import parse_qs, urlsplit
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
callback_agents = []
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
        target = urlsplit(self.path)
        received = self.headers.get('X-Cylo-Callback-Token') or parse_qs(target.query).get('callback_token', [None])[0]
        if target.path == '/v1/apps/installed/900000082' and received == callback_token:
            callbacks.append(received)
            callback_agents.append(self.headers.get('User-Agent'))
            self.send_response(200)
        else:
            self.send_response(404)
        self.end_headers()
    def log_message(self, *args):
        pass


bridge = json.loads(command(['docker', 'network', 'inspect', 'bridge']))[0]['IPAM']['Config'][0]['Gateway']
server = http.server.ThreadingHTTPServer((bridge, 0), Callback)
threading.Thread(target=server.serve_forever, daemon=True).start()


def storage(suffix):
    result = []
    for part in ('torrents', 'database'):
        name = run_id + '-' + suffix + '-' + part
        command(['docker', 'volume', 'create', '--label', 'appbox.release-gate=' + run_id, name])
        volumes.append(name)
        result.append(name)
    return result


def launch(suffix, selected_image, mounts, baseline=False, callback_style='legacy'):
    if baseline:
        # Upgrade needs the old runtime and data formats, not an expensive copy-up
        # of immutable dependencies. Prove those files are usable by UID 1000.
        probe = """import os,stat
assert os.geteuid()==1000
count=0
def failed(error):
    raise error
for folder,dirs,files in os.walk('/usr/src/app',onerror=failed):
    assert os.access(folder,os.R_OK|os.X_OK),'Unreadable legacy directory'
    for name in files:
        path=os.path.join(folder,name)
        mode=os.stat(path).st_mode
        required=os.R_OK|(os.X_OK if mode & 0o111 else 0)
        assert os.access(path,required),'Inaccessible legacy dependency'
        count+=1
assert count>100
print('PASS legacy dependency access: UID 1000 can use',count,'files')
"""
        print(command(['docker', 'run', '--rm', '--network', 'none', '--user', '1000:1000',
                       '--entrypoint', 'python3', selected_image, '-c', probe], timeout=180).decode().strip(), flush=True)
    name = run_id + '-' + suffix
    args = ['docker', 'create', '--platform', 'linux/amd64', '--name', name,
            '--label', 'appbox.release-gate=' + run_id, '--init',
            '--add-host', 'host.docker.internal:host-gateway', '-p', '127.0.0.1::80',
            '-v', mounts[0] + ':/torrents', '-v', mounts[1] + ':/home/flood/.local',
            '-e', 'USERNAME=' + user, '-e', 'PASSWORD=' + password,
            '-e', 'LISTENING_PORT=49160', '-e', 'DHT_PORT=49161',
            '-e', 'APPBOX_API_URL=http://host.docker.internal:' + str(server.server_port) + '/v1']
    if callback_style == 'legacy':
        args += ['-e', 'INSTANCE_ID=900000082?callback_token=' + callback_token]
    else:
        args += ['-e', 'INSTANCE_ID=900000082', '-e', 'CALLBACK_TOKEN=' + callback_token]
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
        # The access probe above permits skipping only the legacy dependency-tree
        # ownership rewrite. Persistent data ownership and the old runtime stay intact.
        ownership = 'chown -R flood:flood /usr/src/app'
        assert source.count(ownership) == 1
        source = source.replace(ownership, 'chown flood:flood /usr/src/app')
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
    # The legacy image recursively chowns bundled dependencies before serving.
    # Allow its first boot longer while retaining the current-image timeout.
    for attempt in range(450 if expected is None else 90):
        try:
            assert request(name, '/')[0] == 200
            version = rpc(name, 'system.client_version')
            if expected:
                assert version == expected, version
            return
        except Exception as error:
            last_error = type(error).__name__ + ': ' + str(error)
            time.sleep(2)
    # Logs are from disposable synthetic-data fixtures only; redact credentials.
    logs = command(['docker', 'logs', '--tail', '400', name]).decode(errors='replace')
    for secret in (password, callback_token, auth):
        logs = logs.replace(secret, '[redacted]')
    logs = re.sub(r'(?im)^.*(?:password|authorization|callback_token).*$','[authentication detail omitted]',logs)
    lines = [line for line in logs.splitlines() if not any(noise in line for noise in ('flood:web-server', 'GET / '))]
    print('\n'.join(lines)[-6000:], flush=True)
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


def check_runtime(name):
    limits = command(['docker', 'inspect', '--format', '{{.HostConfig.Memory}} {{.HostConfig.MemorySwap}} {{.HostConfig.MemoryReservation}} {{.HostConfig.NanoCpus}}', name]).decode().strip()
    assert limits == '0 0 0 0', 'RAM/CPU runtime limits changed'
    for service in ('flood', 'rtorrent', 'rtcheck'):
        pid = command(['docker', 'exec', name, 'supervisorctl', '-c', '/etc/supervisord.conf', 'pid', service]).decode().strip()
        assert pid.isdecimal() and int(pid) > 0
        status = command(['docker', 'exec', name, 'cat', '/proc/' + pid + '/status']).decode()
        assert re.search(r'^Uid:\s+1000\s+1000\s+1000\s+1000$', status, re.M), service + ' is not UID 1000'


def native_user_id(name):
    data = command(['docker', 'exec', name, 'cat', '/home/flood/.local/db/users.db']).decode()
    records = {}
    for line in data.splitlines():
        record = json.loads(line)
        if record.get('$$deleted'):
            records.pop(record['_id'], None)
        elif '_id' in record:
            records[record['_id']] = record
    matches = [record['_id'] for record in records.values() if record.get('username') == user]
    assert len(matches) == 1
    return matches[0]


def bencode(value):
    if isinstance(value, int):
        return b'i' + str(value).encode() + b'e'
    if isinstance(value, bytes):
        return str(len(value)).encode() + b':' + value
    if isinstance(value, dict):
        return b'd' + b''.join(bencode(k) + bencode(v) for k, v in sorted(value.items())) + b'e'
    raise TypeError()


def wait_committed(name, torrent_hash, marker=b''):
    # The known concurrent-save failure is an explicitly accepted release risk.
    # These fixtures exercise restart/upgrade after a completed save.
    probe = """import pathlib,sys,time
p=pathlib.Path('/torrents/config/rtorrent/session')
h=sys.argv[1]
marker=bytes.fromhex(sys.argv[2])
deadline=time.monotonic()+60
while time.monotonic()<deadline:
    sidecar=p/(h+'.torrent.rtorrent')
    if (p/(h+'.torrent')).is_file() and sidecar.is_file() and not list(p.glob(h+'*.new')):
        if not marker or marker in sidecar.read_bytes():
            break
    time.sleep(0.1)
else:
    raise SystemExit('Session save did not commit')
"""
    command(['docker', 'exec', name, 'python3', '-c', probe, torrent_hash, marker.hex()], timeout=75)


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
    wait_committed(name, torrent_hash)
    rpc(name, 'd.custom1.set', torrent_hash, 'release-preserved')
    rpc(name, 'session.save')
    wait_committed(name, torrent_hash, b'release-preserved')
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
    for _ in range(20):
        visible = json.loads(request(name, '/api/torrents')[1])
        if torrent_hash in json.dumps(visible).upper():
            break
        time.sleep(1)
    assert torrent_hash in json.dumps(visible).upper(), 'Persisted torrent missing from Flood API'


try:
    command([sys.executable, str(Path(__file__).with_name('test-callback.py'))])
    details = json.loads(command(['docker', 'image', 'inspect', image]))[0]
    assert details['Architecture'] == 'amd64' and details['Os'] == 'linux'
    version = command(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'flood', image, '--version']).decode()
    assert '4.16.1' in version
    print('ACCEPTED RISK: rTorrent #2017; restart and upgrade tests use completed saves', flush=True)
    fresh = launch('fresh', image, storage('fresh'))
    wait_ready(fresh, '0.16.23')
    check_web(fresh)
    check_runtime(fresh)
    fresh_user_id = native_user_id(fresh)
    assert rpc(fresh, 'dht.override_port') == 49161
    rpc(fresh, 'dht.mode.set', '', 'on')
    for _ in range(20):
        if rpc(fresh, 'dht.port') == 49161:
            break
        time.sleep(1)
    assert rpc(fresh, 'dht.port') == 49161
    rpc(fresh, 'dht.mode.set', '', 'auto')
    assert rpc(fresh, 'network.port_range') == '49160-49160'
    for _ in range(30):
        if callback_token in callbacks:
            break
        time.sleep(1)
    assert callback_token in callbacks, 'Authenticated install callback missing'
    assert 'Appbox-Flood/4.16.1' in callback_agents, 'Identifiable callback user agent missing'
    fixture = seed(fresh)
    print('PASS fresh: versions, HTTP/assets, authentication, RPC, ports, callback and torrent session', flush=True)
    command(['docker', 'restart', '--time', '45', fresh])
    wait_ready(fresh, '0.16.23')
    check_persisted(fresh, fixture)
    check_runtime(fresh)
    assert native_user_id(fresh) == fresh_user_id
    print('PASS restart: data, torrent state, settings and authentication preserved', flush=True)
    # Exercise the separate-token contract too, including the first release's
    # data and a downgrade back to the same engine/UI version.
    current_storage = storage('current')
    current = launch('current', registry.CURRENT, current_storage, callback_style='header')
    wait_ready(current, '0.16.23')
    current_fixture = seed(current)
    current_user_id = native_user_id(current)
    command(['docker', 'stop', '--time', '45', current])
    callbacks.clear()
    repaired = launch('repaired', image, current_storage)
    wait_ready(repaired, '0.16.23')
    check_persisted(repaired, current_fixture)
    assert native_user_id(repaired) == current_user_id
    for _ in range(30):
        if callback_token in callbacks:
            break
        time.sleep(1)
    assert callback_token in callbacks, 'Legacy-format upgrade callback missing'
    command(['docker', 'stop', '--time', '45', repaired])
    command(['docker', 'start', current])
    wait_ready(current, '0.16.23')
    check_persisted(current, current_fixture)
    assert native_user_id(current) == current_user_id
    command(['docker', 'stop', '--time', '45', current])
    print('PASS current-release upgrade and downgrade: data and user preserved; legacy callback acknowledged', flush=True)
    callbacks.clear()
    header = launch('header', image, storage('header'), callback_style='header')
    wait_ready(header, '0.16.23')
    for _ in range(30):
        if callback_token in callbacks:
            break
        time.sleep(1)
    assert callback_token in callbacks, 'Separate-token callback missing'
    print('PASS separate-token callback', flush=True)
    upgrade_storage = storage('upgrade')
    baseline = launch('baseline', registry.PREVIOUS, upgrade_storage, baseline=True)
    wait_ready(baseline, None)
    baseline_fixture = seed(baseline)
    baseline_user_id = native_user_id(baseline)
    command(['docker', 'stop', '--time', '45', baseline])
    upgraded = launch('upgraded', image, upgrade_storage)
    wait_ready(upgraded, '0.16.23')
    check_persisted(upgraded, baseline_fixture)
    assert native_user_id(upgraded) == baseline_user_id
    check_runtime(upgraded)
    print('PASS upgrade: current catalog image data, session, settings and authentication preserved', flush=True)
    replacement = secrets.token_urlsafe(24)
    command(['docker', 'exec', '-i', upgraded, '/scripts/reset-password.py'], data=replacement.encode())
    password = replacement
    auth = 'Basic ' + base64.b64encode((user + ':' + password).encode()).decode()
    openers.pop(upgraded, None)
    wait_ready(upgraded, '0.16.23')
    check_web(upgraded)
    assert native_user_id(upgraded) == baseline_user_id
    print('PASS password reset: HTTP and native Flood authentication updated without replacing user', flush=True)
except Exception as error:
    diagnostic = str(error)
    for secret in (password, callback_token, auth):
        diagnostic = diagnostic.replace(secret, '[redacted]')
    print('FAIL release gate: ' + type(error).__name__ + ': ' + diagnostic, flush=True)
    raise
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
print('PASS required release gates; concurrent-save regression remains an accepted exception', flush=True)
