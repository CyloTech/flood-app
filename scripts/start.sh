#!/usr/bin/env bash
set -x

###########################[ SUPERVISOR SCRIPTS ]###############################

mkdir -p /etc/supervisor/conf.d

cat << EOF > /etc/supervisor/conf.d/rtorrent.conf
[program:rtorrent]
command=/bin/su -s /bin/bash -c "export TERM=screen-256color && ulimit -Sn 65535; /home/flood/.local/rtorrent/0.9.6-PS-1.1-dev/bin/rtorrent-extended" flood
autostart=true
autorestart=true
priority=2
stdout_events_enabled=false
stderr_events_enabled=true
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
EOF

cat << EOF > /etc/supervisor/conf.d/flood.conf
[program:flood]
command=/bin/su -s /bin/bash -c "TERM=xterm cd /usr/src/app/ && npm start -- --host 0.0.0.0 --port 8080" flood
autostart=true
autorestart=true
priority=2
stdout_events_enabled=true
stderr_events_enabled=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
EOF

cat << EOF > /etc/supervisor/conf.d/nginx.conf
[program:nginx]
command=/usr/sbin/nginx
autostart=true
autorestart=true
priority=10
stdout_events_enabled=true
stderr_events_enabled=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
EOF

###########################[ RTORRENT SETUP ]###############################

# arrange dirs and configs
mkdir -p /torrents/downloading
mkdir -p /torrents/completed
mkdir -p /torrents/config/flood
mkdir -p /torrents/config/log
mkdir -p /torrents/config/rtorrent/session
mkdir -p /torrents/config/log/rtorrent
mkdir -p /torrents/config/torrents
mkdir -p /torrents/watch

if [ ! -f /torrents/config/rtorrent/.rtorrent.rc ]; then
    cp /sources/.rtorrent.rc /torrents/config/rtorrent/.rtorrent.rc
    ln -s /torrents/config/rtorrent/.rtorrent.rc /home/flood/
    sed -i 's#LISTENING_PORT#'${LISTENING_PORT}'#g' /torrents/config/rtorrent/.rtorrent.rc
    sed -i 's#DHT_PORT#'${DHT_PORT}'#g' /torrents/config/rtorrent/.rtorrent.rc
else
    sed -i 's#network.port_range.set = [0-9]*-[0-9]*#network.port_range.set = '${LISTENING_PORT}'-'${LISTENING_PORT}'#g' /torrents/config/rtorrent/.rtorrent.rc
    sed -i 's#dht.port.set=[0-9]*#dht.port.set='${DHT_PORT}'#g' /torrents/config/rtorrent/.rtorrent.rc
fi

if [ ! -f /home/flood/.rtorrent.rc ]; then
    ln -s /torrents/config/rtorrent/.rtorrent.rc /home/flood/
fi

rm -f /torrents/config/rtorrent/session/rtorrent.lock

if [[ ! $(grep 'v3.1.0' /torrents/config/rtorrent/.rtorrent.rc) ]]; then
    rm -rf /torrents/config/rtorrent/.rtorrent.rc
    rm -rf /flood-db/users.db
    cp /sources/.rtorrent.rc /torrents/config/rtorrent/.rtorrent.rc
    ln -s /torrents/config/rtorrent/.rtorrent.rc /home/flood/
    sed -i 's#LISTENING_PORT#'${LISTENING_PORT}'#g' /torrents/config/rtorrent/.rtorrent.rc
    sed -i 's#DHT_PORT#'${DHT_PORT}'#g' /torrents/config/rtorrent/.rtorrent.rc
fi

###########################[ FLOOD SETUP ]###############################

rm -f /data/.session/rtorrent.lock

if [ ! -f /torrents/config/flood/config.js ]; then
    rm -f /usr/src/app/config.js
    cp /sources/config.js /torrents/config/flood/config.js
    ln -s /torrents/config/flood/config.js /usr/src/app/
else
    if [[ ! $(grep -q 'v3.1.0' /usr/src/app/config.js) ]]; then
        rm -f /usr/src/app/config.js
        cp /sources/config.js /torrents/config/flood/config.js
        ln -s /torrents/config/flood/config.js /usr/src/app/
    fi
fi

if [[ ! -f /torrents/config/flood/.htpasswd ]]; then
    printf "${USERNAME}:$(openssl passwd -crypt ${PASSWORD})\n" > /torrents/config/flood/.htpasswd && chmod 755 /torrents/config/flood/.htpasswd
fi

ls -d /torrents/* | grep -v home | xargs -d "\n" chown -R flood:flood
chown -R flood:flood /flood-db
chown -R flood:flood /usr/src/app

###########################[ MARK INSTALLED ]###############################

if [ ! -f /etc/app_configured ]; then
    touch /etc/app_configured
    until [[ $(curl -i -H "Accept: application/json" -H "Content-Type:application/json" -X POST "https://api.cylo.io/v1/apps/installed/${INSTANCE_ID}" | grep '200') ]]
        do
        sleep 5
    done
fi

exec /usr/bin/supervisord -n -c /etc/supervisord.conf
