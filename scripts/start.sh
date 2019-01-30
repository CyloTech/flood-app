#!/usr/bin/env bash
set -x

if [[ ! $(grep '3.8-15' /torrents/config/rtorrent/.rtorrent.rc) ]]; then
    rm -rf /torrents/config/rtorrent/.rtorrent.rc
    rm -rf /flood-db/users.db
    cd /usr/src/app
    npm start &

    sleep 10
    URL="http://${DOMAIN}/auth/register"
    echo "*****************************************************************************************"
    echo " Setting Username & Password for ${USERNAME}"
    echo " URL: ${URL}"
    echo "*****************************************************************************************"
    curl --retry 100 -X POST -H "Content-Type: application/json" -d '{"username":"'"${USERNAME}"'", "password": "'"${PASSWORD}"'"}' ${URL};

    echo "*****************************************************************************************"
    echo " Restarting Node/Flood "
    echo "*****************************************************************************************"

    kill -9 $(pgrep node)
fi

if [[ $(grep '3.8-15' /torrents/config/rtorrent/.rtorrent.rc) ]]; then
    sed -i 's/3.8-15/3.8-16/g' /torrents/config/rtorrent/.rtorrent.rc
    rm -rf /flood-db/users.db
    cd /usr/src/app
    npm start &

    sleep 10
    URL="http://${DOMAIN}/auth/register"
    echo "*****************************************************************************************"
    echo " Setting Username & Password for ${USERNAME}"
    echo " URL: ${URL}"
    echo "*****************************************************************************************"
    curl --retry 100 -X POST -H "Content-Type: application/json" -d '{"username":"'"${USERNAME}"'", "password": "'"${PASSWORD}"'"}' ${URL};

    echo "*****************************************************************************************"
    echo " Restarting Node/Flood "
    echo "*****************************************************************************************"

    kill -9 $(pgrep node)
fi

###########################[ SUPERVISOR SCRIPTS ]###############################

mkdir -p /etc/supervisor/conf.d

cat << EOF >> /etc/supervisor/conf.d/rtorrent.conf
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

cat << EOF >> /etc/supervisor/conf.d/flood.conf
[program:flood]
command=/bin/su -s /bin/bash -c "TERM=xterm cd /usr/src/app/ && npm start" flood
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

###########################[ FLOOD SETUP ]###############################

rm -f /data/.session/rtorrent.lock

if [ ! -f /torrents/config/flood/config.js ]; then
    rm -f /usr/src/app/config.js
    cp /sources/config.js /torrents/config/flood/config.js
    ln -s /torrents/config/flood/config.js /usr/src/app/

    cd /usr/src/app
    npm start &

    sleep 10
    URL="http://${DOMAIN}/auth/register"
    echo "*****************************************************************************************"
    echo " Setting Username & Password for ${USERNAME}"
    echo " URL: ${URL}"
    echo "*****************************************************************************************"

    until [[ $(curl -i -X POST -H "Content-Type: application/json" -d '{"username":"'"${USERNAME}"'", "password": "'"${PASSWORD}"'"}' ${URL} | grep '200') ]]
        do
        sleep 5
    done

    echo "*****************************************************************************************"
    echo " Restarting Node/Flood "
    echo "*****************************************************************************************"

    kill -9 $(pgrep node)
else
    # Reset in case of update
    cp /sources/config.js /torrents/config/flood/config.js
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
