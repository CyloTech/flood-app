#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from bootstrap import hash_password

password = sys.stdin.read()
password_file = Path('/torrents/config/flood/.htpasswd')
username = password_file.read_text().split(':', 1)[0]
database = Path('/home/flood/.local/db/users.db')
subprocess.run(['supervisorctl', '-c', '/etc/supervisord.conf', 'stop', 'flood'], check=True, stdout=subprocess.DEVNULL)
try:
    records = {}
    for line in database.read_text().splitlines():
        record = json.loads(line)
        if record.get('$$deleted'):
            records.pop(record['_id'], None)
        elif '_id' in record:
            records[record['_id']] = record
    matches = [record for record in records.values() if record.get('username') == username]
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one default user')
    record = matches[0]
    record['password'] = hash_password(password)
    record['timestamp'] = int(time.time())
    with database.open('a') as output:
        output.write(json.dumps(record) + '\n')
        output.flush()
        os.fsync(output.fileno())
    subprocess.run(['htpasswd', '-iB', str(password_file), username], input=(password + '\n').encode(),
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
finally:
    subprocess.run(['supervisorctl', '-c', '/etc/supervisord.conf', 'start', 'flood'], check=True, stdout=subprocess.DEVNULL)
