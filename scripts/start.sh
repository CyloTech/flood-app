#!/usr/bin/env bash
set -x

###########################[ SUPERVISOR SCRIPTS ]###############################

if [ ! -f /etc/app_configured ]; then
    mkdir -p /etc/supervisor/conf.d

cat << EOF >> /etc/supervisor/conf.d/rtorrent.conf
[program:rtorrent]
command=/bin/su -s /bin/bash -c "TERM=xterm rtorrent" flood
autostart=true
autorestart=true
priority=1
stdout_events_enabled=true
stderr_events_enabled=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
EOF

cat << EOF >> /etc/supervisor/conf.d/flood.conf
[program:flood]
command=/bin/su -s /bin/bash -c "TERM=xterm /usr/flood/server/bin/www" flood
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
fi

###########################[ RTORRENT SETUP ]###############################

# arrange dirs and configs
if [ ! -f /etc/app_configured ]; then
    mkdir -p /torrents/downloading
    mkdir -p /torrents/completed
    mkdir -p /torrents/config/flood
    mkdir -p /torrents/config/log
    mkdir -p /torrents/config/rtorrent/session
    mkdir -p /torrents/config/log/rtorrent
    mkdir -p /torrents/config/torrents
    mkdir -p /torrents/watch
fi

if [ ! -f /etc/app_configured ]; then
    cp /sources/.rtorrent.rc /torrents/config/rtorrent/.rtorrent.rc
    ln -s /torrents/config/rtorrent/.rtorrent.rc /home/flood/
    sed -i 's#LISTENING_PORT#'${LISTENING_PORT}'#g' /torrents/config/rtorrent/.rtorrent.rc
    sed -i 's#DHT_PORT#'${DHT_PORT}'#g' /torrents/config/rtorrent/.rtorrent.rc
fi

rm -f /torrents/config/rtorrent/session/rtorrent.lock

###########################[ FLOOD SETUP ]###############################

rm -f /data/.session/rtorrent.lock

if [ ! -f /etc/app_configured ]; then
    cp /sources/config.js /torrents/config/flood/config.js
    ln -s /torrents/config/flood/config.js /usr/flood/

    cd /usr/flood
    exec /usr/flood/server/bin/www &

    sleep 10
    URL="http://${DOMAIN}/auth/register"
    echo "*****************************************************************************************"
    echo " Setting Username & Password for ${USERNAME}"
    echo " URL: ${URL}"
    echo "*****************************************************************************************"
    curl -X POST -H "Content-Type: application/json" -d '{"username":"'"${USERNAME}"'", "password": "'"${PASSWORD}"'"}' ${URL};

    echo "*****************************************************************************************"
    echo " Restarting Node/Flood "
    echo "*****************************************************************************************"

    kill -9 $(pgrep node)
fi

chown -R flood:flood /torrents
chown -R flood:flood /flood-db
chown -R flood:flood /usr/flood

###########################[ MARK INSTALLED ]###############################

if [ ! -f /etc/app_configured ]; then
    touch /etc/app_configured
    curl -i -H "Accept: application/json" -H "Content-Type:application/json" -X POST "https://api.cylo.io/v1/apps/installed/$INSTANCE_ID"
fi

exec /usr/bin/supervisord -n -c /etc/supervisord.conf
