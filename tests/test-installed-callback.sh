#!/usr/bin/env bash
# Tests for the Appbox installed callback, run against a local mock API (needs
# bash, curl and python3; no Docker). Flood sends the callback from
# scripts/callback.py, a supervisord program that runs after the app starts,
# so it never blocks startup. These cases run that script for real (only the
# app readiness check is stubbed and the marker moved into a sandbox):
#   - 2xx is accepted once and marks the instance configured;
#   - 408, 429 and 5xx are retried;
#   - any other status (401 once the token is used or cleared, 403, 404) is
#     logged once, not retried, and exits 0 so supervisord does not restart
#     the program;
#   - a restart with the marker present sends nothing;
#   - the callback token never appears in the output.
# scripts/test-callback.py (unit tests with a mocked urlopen) still applies.
#
# Usage: tests/test-installed-callback.sh
set -u

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
token_id='999?callback_token=querytoken0123456789'
header_token='headertoken0123456789'

# Answers GET with 200 (readiness) and each POST with the next status from a
# comma-separated list, logging what it received.
mock_server='
import http.server, json, os, sys
port, codes, log = int(sys.argv[1]), [int(c) for c in sys.argv[2].split(",")], sys.argv[3]
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
    def do_POST(self):
        seen = sum(1 for _ in open(log)) if os.path.exists(log) else 0
        code = codes[min(seen, len(codes) - 1)]
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode() if length else ""
        with open(log, "a") as f:
            f.write(json.dumps({"path": self.path, "code": code, "body": body,
                                "token": self.headers.get("X-Cylo-Callback-Token", "")}) + "\n")
        self.send_response(code)
        self.end_headers()
    def log_message(self, *args):
        pass
http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
'

failures=0
work=""
server=""

pass() { echo "ok   $*"; }
fail() {
    echo "FAIL $*"
    [[ -f "${work}/output" ]] && sed 's/^/     /' "${work}/output"
    failures=$((failures + 1))
}

start_mock() {
    work="$(mktemp -d)"
    port=$((20000 + RANDOM % 20000))
    python3 -c "${mock_server}" "${port}" "$1" "${work}/requests" &
    server=$!
    for _ in $(seq 1 50); do
        curl -s -o /dev/null "http://127.0.0.1:${port}/" && return 0
        sleep 0.1
    done
    echo "mock API did not start" >&2
    exit 2
}

stop_mock() {
    kill "${server}" 2>/dev/null
    wait "${server}" 2>/dev/null
    rm -rf "${work}"
}

# Run a command, killing it (exit 124) if it is still running after $1 seconds,
# so a callback that never stops fails the test instead of hanging it.
run_limited() {
    local limit=$1 pid ticks=0
    shift
    "$@" &
    pid=$!
    while kill -0 "${pid}" 2>/dev/null && [[ "${ticks}" -lt $((limit * 10)) ]]; do
        sleep 0.1
        ticks=$((ticks + 1))
    done
    if kill -0 "${pid}" 2>/dev/null; then
        kill "${pid}" 2>/dev/null
        wait "${pid}" 2>/dev/null
        return 124
    fi
    wait "${pid}"
}

request_count() { cat "${work}/requests" 2>/dev/null | wc -l | tr -d ' '; }
token_logged() { grep -cE 'querytoken|headertoken' "${work}/output"; }

# --- scripts/callback.py --------------------------------------------------------

callback_case() {
    local codes=$1 want_requests=$2 want_marker=$3 state=${4:-fresh}
    # The catalogue passes the token in INSTANCE_ID; newer entries pass a bare
    # ID and CALLBACK_TOKEN.
    local instance="${token_id}" token="" want_token=querytoken0123456789
    if [[ "${state}" == header ]]; then
        instance=999 token="${header_token}" want_token="${header_token}"
    fi
    start_mock "${codes}"
    mkdir -p "${work}/scripts"
    sed "s|Path('/etc/app_configured')|Path('${work}/app_configured')|" \
        "${repo_root}/scripts/callback.py" >"${work}/scripts/callback.py"
    printf 'def healthy():\n    pass\n' >"${work}/scripts/healthcheck.py"
    [[ "${state}" == restart ]] && touch "${work}/app_configured"
    run_limited 30 env INSTANCE_ID="${instance}" CALLBACK_TOKEN="${token}" APPBOX_API_URL="http://127.0.0.1:${port}/v1" \
        python3 "${work}/scripts/callback.py" >"${work}/output" 2>&1
    local rc=$? requests have_marker=no
    requests=$(request_count)
    [[ -f "${work}/app_configured" ]] && have_marker=yes
    if [[ "${rc}" == 0 && "${requests}" == "${want_requests}" && "${have_marker}" == "${want_marker}" \
        && "$(token_logged)" == 0 ]]; then
        pass "callback.py ${state} codes=${codes}: exit=0 requests=${requests} marker=${have_marker}"
    else
        fail "callback.py ${state} codes=${codes}: exit=${rc} requests=${requests}/${want_requests} marker=${have_marker}/${want_marker} token_logged=$(token_logged)"
    fi
    if [[ "${want_requests}" != 0 ]] && ! python3 - "${work}/requests" "${want_token}" <<'PY'
import json, sys
for line in open(sys.argv[1]):
    req = json.loads(line)
    assert req["path"] == "/v1/apps/installed/999", req
    assert req["token"] == sys.argv[2], req
PY
    then
        fail "callback.py codes=${codes}: request path or X-Cylo-Callback-Token"
    fi
    stop_mock
}

callback_case 200 1 yes
callback_case 204 1 yes
callback_case 401 1 no
callback_case 403 1 no
callback_case 404 1 no
callback_case 503,200 2 yes
callback_case 429,200 2 yes
callback_case 200 0 yes restart
callback_case 401 1 no header
callback_case 200 1 yes header

exit "${failures}"
