#!/usr/bin/env python3
from datetime import datetime
import sys
from io import StringIO
import random
import time
import xmlrpc.client, urllib.parse, socket
from urllib.parse import urlparse
import os
import pwd
import getpass
import re

# Append 'scgi' scheme to urllib's list of known protocols
urllib.parse.uses_netloc.append('scgi')

# PID-based lock
lockfile_path = "/tmp/script.lock"

def acquire_lock(lockfile):
    if os.path.exists(lockfile):
        with open(lockfile, 'r') as f:
            pid = f.read().strip()
        if os.path.exists("/proc/{}".format(pid)):
            print("Script is already running with PID {}. Exiting.".format(pid))
            sys.exit(0)
        else:
            print("Stale lock file found. Overwriting with new PID.")
    
    with open(lockfile, 'w') as f:
        f.write(str(os.getpid()))

def release_lock(lockfile):
    if os.path.exists(lockfile):
        os.remove(lockfile)

def do_scgi_xmlrpc_request(host, methodname, params=()):
    xmlreq = xmlrpc.client.dumps(params, methodname)
    xmlresp = SCGIRequest(host).send(xmlreq)
    return xmlresp

def do_scgi_xmlrpc_request_py(host, methodname, params=()):
    xmlresp = do_scgi_xmlrpc_request(host, methodname, params)
    return xmlrpc.client.loads(xmlresp)[0][0]

class SCGIRequest(object):
    def __init__(self, url):
        self.url = url
        self.resp_headers = []

    def __send(self, scgireq):
        # Assuming `self.url` is now just a file path for Unix sockets
        path = self.url
        if os.path.exists(path):
            print(f"Debug: Attempting Unix socket connection to {path}")
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(path)
        else:
            print(f"Error: Unix socket file {path} does not exist.")
            return ""

        # Send the SCGI request
        sock.sendall(scgireq.encode('utf-8'))
        recvdata = resp = sock.recv(1024)
        while recvdata:
            recvdata = sock.recv(1024)
            resp += recvdata
        sock.close()
        return resp.decode('utf-8')
    def send(self, data):
        scgiresp = self.__send(self.add_required_scgi_headers(data))
        resp, self.resp_headers = self.get_scgi_resp(scgiresp)
        return resp
    @staticmethod
    def encode_netstring(string):
        return '%d:%s,' % (len(string), string)
    @staticmethod
    def make_headers(headers):
        return '\x00'.join(['%s\x00%s' % t for t in headers]) + '\x00'
    @staticmethod
    def add_required_scgi_headers(data, headers=[]):
        headers = SCGIRequest.make_headers([('CONTENT_LENGTH', str(len(data))), ('SCGI', '1'),] + headers)
        enc_headers = SCGIRequest.encode_netstring(headers)
        return enc_headers + data
    @staticmethod
    def gen_headers(file):
        line = file.readline().rstrip()
        while line.strip():
            yield line
            line = file.readline().rstrip()
    @staticmethod
    def get_scgi_resp(resp):
        fresp = StringIO(resp)
        headers = []
        for line in SCGIRequest.gen_headers(fresp):
            headers.append(line.split(': ', 1))
        xmlresp = fresp.read()
        return (xmlresp, headers)

class RTorrentXMLRPCClient(object):
    def __init__(self, url, methodname=''):
        self.url = url
        self.methodname = methodname
    def __call__(self, *args):
        scheme, netloc, path, query, frag = urllib.parse.urlsplit(self.url)
        xmlreq = xmlrpc.client.dumps(args, self.methodname)
        if scheme == 'scgi':
            xmlresp = SCGIRequest(self.url).send(xmlreq)
            return xmlrpc.client.loads(xmlresp)[0][0]
        elif scheme in ('http', 'https', ''):
            raise Exception('Unsupported protocol')
        else:
            raise Exception('Unsupported protocol')
    def __getattr__(self, attr):
        methodname = '.'.join([self.methodname, attr]) if self.methodname else attr
        return RTorrentXMLRPCClient(self.url, methodname)

def convert_params_to_native(params):
    cparams = []
    for param in params:
        if len(param) < 2 or param[1] != '/':
            cparams.append(param)
            continue
        if param[0] == 'i':
            ptype = int
        elif param[0] == 'b':
            ptype = lambda x: x.lower() in ('true', '1')
        elif param[0] == 's':
            ptype = str
        else:
            cparams.append(param)
            continue
        cparams.append(ptype(param[2:]))
    return tuple(cparams)

def is_private(url):
    pattern1 = '(http|https|udp)://[a-z0-9-.]+\.[a-z]{2,4}((:(\d){2,5})|).*/an.*\?.+=.+'
    pattern2 = '(http|https|udp)://[a-z0-9-.]+\.[a-z]{2,4}((:(\d){2,5})|)/.*[0-9a-z]{8,32}/an'
    result = True if re.match(pattern1, url) or re.match(pattern2, url) else False
    return result

def check_torrent(hash):
    host = '/torrents/config/rtorrent/rtorrent.sock'  # Directly use the socket file path
    try:
        methodname = 'd.state'
        respxml = do_scgi_xmlrpc_request(host, methodname, convert_params_to_native(['s/{}'.format(hash)]))
        torrent_active = bool(xmlrpc.client.loads(respxml)[0][0])

        methodname = 'd.complete'
        respxml = do_scgi_xmlrpc_request(host, methodname, convert_params_to_native(['s/{}'.format(hash)]))
        torrent_complete = bool(xmlrpc.client.loads(respxml)[0][0])

        methodname = 'd.is_private'
        respxml = do_scgi_xmlrpc_request(host, methodname, convert_params_to_native(['s/{}'.format(hash)]))
        torrent_private = bool(xmlrpc.client.loads(respxml)[0][0])

        if torrent_active and torrent_complete and not torrent_private:
            methodname = 'd.tracker_size'
            respxml = do_scgi_xmlrpc_request(host, methodname, convert_params_to_native(['s/{}'.format(hash)]))
            # print('Tracker count:', xmlrpc.client.loads(respxml)[0][0])
            tracker_cnt = int(xmlrpc.client.loads(respxml)[0][0])

            is_public = True
            for t in range(tracker_cnt):
                methodname = 't.url'
                target = f"{hash}:t{t}"  # Format the target as specified
                # print('Checking tracker {} of {}'.format(t, hash))
                respxml = do_scgi_xmlrpc_request(host, methodname, (target,))
                # print ('Tracker URL:', xmlrpc.client.loads(respxml)[0][0])
                tracker = xmlrpc.client.loads(respxml)[0][0]
                # print('Tracker is private:', is_private(tracker))
                if is_private(tracker):
                    is_public = False
                    break

            if is_public:
                methodname = 'd.try_close'
                respxml = do_scgi_xmlrpc_request(host, methodname, convert_params_to_native(['s/{}'.format(hash)]))
                result = not bool(xmlrpc.client.loads(respxml)[0][0])
                if result:
                    print('{} {} stopped.'.format(datetime.now().isoformat(), hash))
    except xmlrpc.client.Fault as e:
        print('ERROR:', e)

def get_torrents():
    host = '/torrents/config/rtorrent/rtorrent.sock'  # Directly use the socket file path
    try:
        methodname = 'download_list'
        respxml = do_scgi_xmlrpc_request(host, methodname, convert_params_to_native(['s/{}'.format('')]))
        download_list = xmlrpc.client.loads(respxml)[0][0]
        return download_list
    except xmlrpc.client.Fault as e:
        print('ERROR:', e)

def daemon_loop():
    while True:
        torrents = get_torrents()
        if len(torrents) > 0:
            print('{} torrent(s) found.'.format(len(torrents)))
            for torrent in torrents:
                print('Checking: {}'.format(torrent))
                check_torrent(torrent)
        else:
            print('No torrents found, doing nothing.')

        # Random delay between 1 and 2 minutes
        jitter = random.randint(60, 120)
        print("Delaying next execution by {} seconds.".format(jitter))
        time.sleep(jitter)

if __name__ == "__main__":
    acquire_lock(lockfile_path)
    try:
        daemon_loop()
    finally:
        release_lock(lockfile_path)
