#!/usr/bin/env python3
import socket
import sys
import urllib.request
import xmlrpc.client


def rpc(method, *params):
    body = xmlrpc.client.dumps(params, methodname=method).encode()
    header = b'CONTENT_LENGTH\0' + str(len(body)).encode() + b'\0SCGI\x001\0'
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(5)
        connection.connect('/torrents/config/rtorrent/rtorrent.sock')
        connection.sendall(str(len(header)).encode() + b':' + header + b',' + body)
        data = b''
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                break
            data += chunk
    return xmlrpc.client.loads(data[data.index(b'<?xml'):])[0][0]


def healthy():
    assert rpc('system.client_version')
    with urllib.request.urlopen('http://127.0.0.1:3000/', timeout=5) as response:
        assert response.status == 200


if __name__ == '__main__':
    try:
        healthy()
    except Exception:
        sys.exit(1)
