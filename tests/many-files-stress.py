#!/usr/bin/env python3
"""Start, stop, erase and reload many-file torrents and count rTorrent crashes.

rTorrent 0.16.23 aborted on Appbox when torrents with over a thousand files
were started and removed: its open-file cache kept pointers to files of erased
torrents (fixed in libtorrent 0.16.24), and erasing a torrent could trip the
size_pex assertion (fixed in 0.16.25). This drives that workload against an
image in a disposable container and prints a JSON summary.

Usage: tests/many-files-stress.py IMAGE CYCLES
"""
import json
import secrets
import subprocess
import sys
import time
import uuid

INNER = r'''
import hashlib, json, os, socket, sys, time, xmlrpc.client as x

SOCK = "/torrents/config/rtorrent/rtorrent.sock"
BASE = "/torrents/downloading"

def call(method, *params):
    body = x.dumps(params, method).encode()
    head = b"CONTENT_LENGTH\0%d\0SCGI\x001\0" % len(body)
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(60)
    s.connect(SOCK)
    s.sendall(b"%d:%s,%s" % (len(head), head, body))
    reply = b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        reply += chunk
    s.close()
    return x.loads(reply.split(b"\r\n\r\n", 1)[1])[0][0]

def bencode(v):
    if isinstance(v, int):
        return b"i%de" % v
    if isinstance(v, bytes):
        return b"%d:%s" % (len(v), v)
    if isinstance(v, list):
        return b"l" + b"".join(bencode(i) for i in v) + b"e"
    return b"d" + b"".join(bencode(k) + bencode(v[k]) for k in sorted(v)) + b"e"

def make(name, count, size=4096, piece=65536):
    root = os.path.join(BASE, name)
    files, blob = [], bytearray()
    for i in range(count):
        rel = ["d%03d" % (i // 100), "f%05d.bin" % i]
        data = hashlib.sha256(b"%s-%d" % (name.encode(), i)).digest() * (size // 32)
        os.makedirs(os.path.join(root, rel[0]), exist_ok=True)
        with open(os.path.join(root, *rel), "wb") as f:
            f.write(data)
        files.append({b"length": size, b"path": [p.encode() for p in rel]})
        blob += data
    pieces = b"".join(hashlib.sha1(blob[i:i + piece]).digest() for i in range(0, len(blob), piece))
    info = {b"name": name.encode(), b"piece length": piece, b"pieces": pieces, b"files": files, b"private": 1}
    path = "/tmp/%s.master" % name
    with open(path, "wb") as f:
        f.write(bencode({b"announce": b"http://127.0.0.1:9/announce", b"info": info}))
    return path, hashlib.sha1(bencode(info)).hexdigest().upper()

def wait_socket(limit=120):
    end = time.time() + limit
    while time.time() < end:
        try:
            call("system.client_version")
            return
        except Exception:
            time.sleep(1)
    raise SystemExit("rTorrent did not answer")

def wait_complete(h, limit=300):
    end = time.time() + limit
    while time.time() < end:
        try:
            if h not in call("download_list"):
                return False
            if call("d.complete", h) == 1 and call("d.hashing", h) == 0:
                return True
        except Exception:
            wait_socket()
            return False
        time.sleep(0.5)
    return False

def load(path, h, cycle):
    # rTorrent deletes the loaded .torrent when the download is erased
    # (event.download.erased runs d.delete_tied), so load a fresh copy.
    copy = path[:-len(".master")] + "-%d.torrent" % cycle
    with open(path, "rb") as src, open(copy, "wb") as dst:
        dst.write(src.read())
    call("load.start", "", copy)
    end = time.time() + 60
    while h not in call("download_list"):
        if time.time() > end:
            return False
        time.sleep(0.2)
    return True

def erase(h):
    # d.erase finishes asynchronously; reloading before it does is ignored.
    call("d.erase", h)
    end = time.time() + 60
    while h in call("download_list") and time.time() < end:
        time.sleep(0.2)

cycles = int(sys.argv[1])
wait_socket()
a = make("many-a", 2600)
b = make("many-b", 1200)
peak = 0
done = 0
errors = []
for cycle in range(cycles):
    try:
        for path, h in (a, b):
            if h not in call("download_list") and not load(path, h, cycle):
                errors.append("cycle %d: %s did not load" % (cycle, h[:8]))
        for path, h in (a, b):
            if not wait_complete(h):
                errors.append("cycle %d: %s not complete" % (cycle, h[:8]))
        peak = max(peak, call("network.open_files"))
        call("d.stop", a[1]); call("d.close", a[1]); call("d.start", a[1])
        wait_complete(a[1])
        erase(b[1])
        erase(a[1])
        done += 1
    except Exception as error:
        errors.append("cycle %d: %s" % (cycle, type(error).__name__))
        wait_socket()
try:
    wait_socket()
    max_files = call("network.max_open_files")
except BaseException:
    max_files = None
print(json.dumps({"cycles": done, "open_files_peak": peak,
                  "max_open_files": max_files, "errors": errors[:10]}))
'''


def run(args, data=None, timeout=600):
    p = subprocess.run(args, input=data, capture_output=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError('command failed: ' + p.stderr.decode(errors='replace')[-800:])
    return p.stdout.decode()


def rtorrent_exits(name):
    log = run(['docker', 'exec', name, 'cat', '/var/log/supervisor/supervisord.log'])
    return [line for line in log.splitlines() if 'exited: rtorrent' in line]


def main():
    if len(sys.argv) != 3 or not sys.argv[2].isdecimal():
        raise SystemExit(__doc__)
    image, cycles = sys.argv[1], sys.argv[2]
    run_id = 'flood-stress-' + uuid.uuid4().hex[:12]
    volume = run_id + '-torrents'
    name = run_id
    created = []
    try:
        run(['docker', 'volume', 'create', '--label', 'appbox.release-gate=' + run_id, volume])
        created.append(('volume', volume))
        run(['docker', 'create', '--platform', 'linux/amd64', '--name', name, '--init',
             '--label', 'appbox.release-gate=' + run_id, '-v', volume + ':/torrents',
             '-e', 'USERNAME=stress', '-e', 'PASSWORD=' + secrets.token_urlsafe(18),
             '-e', 'LISTENING_PORT=49170', '-e', 'DHT_PORT=49171',
             '-e', 'INSTANCE_ID=900000083', '-e', 'SKIP_APPBOX_CALLBACK=1', image])
        created.append(('container', name))
        run(['docker', 'start', name])
        started = time.time()
        while True:
            try:
                run(['docker', 'exec', name, 'test', '-S', '/torrents/config/rtorrent/rtorrent.sock'])
                break
            except RuntimeError:
                if time.time() - started > 120:
                    raise
                time.sleep(1)
        before = rtorrent_exits(name)
        try:
            out = run(['docker', 'exec', '-i', '-u', 'flood', name, 'python3', '-I', '-', cycles],
                      data=INNER.encode(), timeout=3600)
            summary = json.loads(out.strip().splitlines()[-1])
        except (RuntimeError, ValueError, IndexError) as error:
            summary = {'cycles': 0, 'errors': ['driver: ' + str(error)[-300:]], 'max_open_files': None}
        exits = rtorrent_exits(name)[len(before):]
        summary['rtorrent_exits'] = len(exits)
        summary['exit_lines'] = [line.split(' WARN ')[-1].split(' INFO ')[-1] for line in exits[:5]]
        # Synthetic fixture only: keep rTorrent's own abort messages.
        logs = subprocess.run(['docker', 'logs', name], capture_output=True, timeout=60)
        aborts = [line.strip()[:220] for line in (logs.stdout + logs.stderr).decode(errors='replace').splitlines()
                  if 'Assertion' in line or 'internal_error' in line]
        summary['abort_messages'] = sorted(set(aborts))[:5]
        summary['image'] = image
        print(json.dumps(summary), flush=True)
    finally:
        for kind, item in reversed(created):
            label = run(['docker', kind, 'inspect', '--format',
                         '{{index .Config.Labels "appbox.release-gate"}}' if kind == 'container'
                         else '{{index .Labels "appbox.release-gate"}}', item]).strip()
            if label == run_id:
                run(['docker', 'rm', '-f', '-v', item] if kind == 'container' else ['docker', 'volume', 'rm', item])


if __name__ == '__main__':
    main()
