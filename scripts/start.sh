#!/usr/bin/env bash
set -euo pipefail
umask 0027

for port in "${LISTENING_PORT:?LISTENING_PORT is required}" "${DHT_PORT:?DHT_PORT is required}"; do
    [[ "$port" =~ ^[0-9]{1,5}$ ]] && ((10#$port >= 1 && 10#$port <= 65535)) || exit 1
done

for dir in /torrents/downloading /torrents/completed /torrents/watch \
    /torrents/config/flood /torrents/config/rtorrent/session \
    /torrents/config/log/rtorrent /torrents/config/torrents /home/flood/.local; do
    mkdir -p "$dir"
    chown flood:flood "$dir"
done
# Parent config directories are created by the root entrypoint.
chown flood:flood /torrents/config /torrents/config/rtorrent /torrents/config/log

config=/torrents/config/rtorrent/.rtorrent.rc
if [[ ! -f "$config" ]]; then
    cp /sources/.rtorrent.rc "$config"
elif [[ ! -e "${config}.pre-4.16.1" ]]; then
    cp -p "$config" "${config}.pre-4.16.1"
fi
# Keep configuration and session state; translate commands from the old fork.
sed -i -E \
    -e "s/LISTENING_PORT/${LISTENING_PORT}/g" \
    -e "s/DHT_PORT/${DHT_PORT}/g" \
    -e 's/^dht\.port\.set[[:space:]]*=/dht.override_port.set =/' \
    -e 's/^fs\.mkdir(\.recursive)?[[:space:]]*=/execute.nothrow = mkdir, -p,/' \
    -e 's/^network\.max_open_sockets\.set[[:space:]]*=[[:space:]]*300[[:space:]]*$/network.max_open_sockets.set = 512/' \
    -e 's/^(encoding\.add[[:space:]]*=[[:space:]]*utf-?8[[:space:]]*)$/# UTF-8 is native in rTorrent 0.16: \1/I' \
    "$config"
chown flood:flood "$config"
ln -sfn "$config" /etc/rtorrent/rtorrent.rc
rm -f /torrents/config/rtorrent/session/rtorrent.lock /torrents/config/rtorrent/rtorrent.sock
# The monitor PID belongs to the previous container process namespace after restart.
rm -f /tmp/script.lock

if [[ ! -f /torrents/config/flood/.htpasswd ]]; then
    : "${USERNAME:?USERNAME is required}" "${PASSWORD:?PASSWORD is required}"
    printf '%s\n' "$PASSWORD" | htpasswd -iBc /torrents/config/flood/.htpasswd "$USERNAME" >/dev/null 2>&1
fi
chown flood:flood /torrents/config/flood/.htpasswd
chmod 640 /torrents/config/flood/.htpasswd
/scripts/bootstrap.py
nginx -t
exec /usr/bin/supervisord -n -c /etc/supervisord.conf
