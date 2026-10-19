#!/usr/bin/env python3
import os
from pathlib import Path
import time
import urllib.request
from urllib.error import HTTPError
from urllib.parse import parse_qs
from healthcheck import healthy

marker = Path('/etc/app_configured')
if marker.exists():
    raise SystemExit(0)
for attempt in range(300):
    try:
        healthy()
        break
    except Exception:
        time.sleep(2)
else:
    raise SystemExit('App readiness timed out')

if os.environ.get('SKIP_APPBOX_CALLBACK') != '1':
    instance, separator, query = os.environ.get('INSTANCE_ID', '').partition('?')
    if not instance.isascii() or not instance.isdecimal():
        raise SystemExit('INSTANCE_ID is required')
    token = os.environ.get('CALLBACK_TOKEN', '')
    if separator:
        # Legacy catalogue entries carry the token in INSTANCE_ID. Send it in
        # the header so it does not appear in the callback URL or access logs.
        try:
            values = parse_qs(query, strict_parsing=True, max_num_fields=1)
            if set(values) != {'callback_token'} or len(values['callback_token']) != 1:
                raise ValueError()
            query_token = values['callback_token'][0]
            if token and token != query_token:
                raise ValueError()
            token = query_token
        except ValueError:
            raise SystemExit('Invalid callback configuration') from None
    if not token:
        raise SystemExit('Callback token is required')
    url = os.environ.get('APPBOX_API_URL', 'https://api.cylo.net/v1').rstrip('/') + '/apps/installed/' + instance
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json',
               'User-Agent': 'Appbox-Flood/4.16.1'}
    headers['X-Cylo-Callback-Token'] = token
    for attempt in range(120):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=b'{}', headers=headers), timeout=15) as response:
                if not 200 <= response.status < 300:
                    raise ValueError('Callback status')
            break
        except HTTPError as error:
            # Only 408, 429 and 5xx can succeed later. The API accepts one
            # installed callback per install or update and rejects the rest
            # (401 once the token is used or cleared), so any other status is
            # final. Exit 0 so supervisord does not start the loop again.
            if error.code not in (408, 429) and error.code < 500:
                print('Install callback rejected with HTTP %d; not retrying' % error.code, flush=True)
                raise SystemExit(0)
            time.sleep(5)
        except Exception:
            time.sleep(5)
    else:
        raise SystemExit('Install callback timed out')
marker.touch()
print('Flood ready; installation acknowledged', flush=True)
