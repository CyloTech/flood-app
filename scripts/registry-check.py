#!/usr/bin/env python3
"""Fail closed unless the authenticated registry confirms this new tag is absent."""
import subprocess
import sys

EXPECTED = 'repo.cylo.net/flood:4.16.1-0.16.25'
# 4.16.1-0.16.23-2, the catalogue default this release replaces.
CURRENT = 'repo.cylo.net/flood@sha256:2714c4f24faabe999a1c23cb75110f006c3dcf81216ef5c8b9ffe96e38a784f5'
PREVIOUS = 'repo.cylo.net/flood@sha256:1e94603a770407d55e148660712ee8c94a0599d325f98c094221ed4193cc78de'


def require_absent(image):
    if image != EXPECTED:
        raise RuntimeError('Unexpected image reference')
    known = subprocess.run(['docker', 'manifest', 'inspect', PREVIOUS], capture_output=True, text=True, timeout=90)
    if known.returncode:
        raise RuntimeError('Authenticated registry baseline read failed; state is indeterminate')
    result = subprocess.run(['docker', 'manifest', 'inspect', image], capture_output=True, text=True, timeout=90)
    if result.returncode == 0:
        raise RuntimeError('Release tag exists; refusing replacement')
    if result.stderr.strip() != 'no such manifest: ' + image:
        raise RuntimeError('Registry response is indeterminate; refusing publication')
    print('PASS registry: baseline readable and exact release tag definitively absent', flush=True)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: registry-check.py IMAGE')
    require_absent(sys.argv[1])
