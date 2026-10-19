#!/usr/bin/env python3
"""Create only a missing Flood user database; never replace persisted users."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import time


def hash_password(password):
    return subprocess.run(['argon2', secrets.token_hex(16), '-id', '-t', '256', '-m', '9', '-p', '1', '-e'],
                          input=password.encode(), capture_output=True, check=True).stdout.decode().strip()


if __name__ == '__main__':
    database = Path('/home/flood/.local/db/users.db')
    if not database.exists():
        username = os.environ['USERNAME']
        record = {'username': username, 'password': hash_password(os.environ['PASSWORD']),
                  'client': {'client': 'rTorrent', 'type': 'socket', 'version': 1,
                             'socket': '/torrents/config/rtorrent/rtorrent.sock'},
                  'level': 10, 'timestamp': int(time.time()), '_id': secrets.token_hex(8)}
        database.parent.mkdir(parents=True, exist_ok=True)
        with database.open('x') as output:
            output.write(json.dumps({'$$indexCreated': {'fieldName': 'username', 'unique': True, 'sparse': False}}) + '\n')
            output.write(json.dumps(record) + '\n')
        os.chown(database.parent, 1000, 1000)
        os.chown(database, 1000, 1000)
        os.chmod(database, 0o600)
