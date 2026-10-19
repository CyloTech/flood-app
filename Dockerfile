# syntax=docker/dockerfile:1
FROM debian:trixie-slim AS rtorrent-build
ARG RTORRENT_VERSION=0.16.23
ARG LIBTORRENT_SHA256=888509f8836d2f0cf779f0e3cfcd2514f88ef8946a20e88b1ad3de9cbd900832
ARG RTORRENT_SHA256=be8679cdc14be9bfe7044e09d50c822a85805ca79554436464822cd34a11798a
RUN apt-get update \
    && apt-get download libeatmydata1 \
    && dpkg-deb -x libeatmydata1_*.deb /tmp/build-eatmydata \
    && build_eatmydata="$(find /tmp/build-eatmydata -name libeatmydata.so -print -quit)" \
    && test -n "$build_eatmydata" \
    && LD_PRELOAD="$build_eatmydata" apt-get install -y --no-install-recommends \
    ca-certificates curl build-essential pkg-config libssl-dev libcurl4-openssl-dev \
    libncurses-dev libsigc++-3.0-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/* /tmp/build-eatmydata /libeatmydata1_*.deb
WORKDIR /build
RUN curl -fsSL -o libtorrent.tar.gz "https://github.com/rakshasa/rtorrent/releases/download/v${RTORRENT_VERSION}/libtorrent-${RTORRENT_VERSION}.tar.gz" \
    && echo "${LIBTORRENT_SHA256}  libtorrent.tar.gz" | sha256sum -c - \
    && tar xzf libtorrent.tar.gz && cd "libtorrent-${RTORRENT_VERSION}" \
    && ./configure --enable-aligned && make -j4 && make install
RUN curl -fsSL -o rtorrent.tar.gz "https://github.com/rakshasa/rtorrent/releases/download/v${RTORRENT_VERSION}/rtorrent-${RTORRENT_VERSION}.tar.gz" \
    && echo "${RTORRENT_SHA256}  rtorrent.tar.gz" | sha256sum -c - \
    && tar xzf rtorrent.tar.gz && cd "rtorrent-${RTORRENT_VERSION}" \
    && ./configure --with-xmlrpc-tinyxml2 --with-ncurses && make -j4 && make install

FROM debian:trixie-slim
ARG FLOOD_VERSION=4.16.1
ARG FLOOD_SHA256=c979f1fd6cf309d143c2c7e9e13ae470f880df72a38f96f4bb4f813175c4ecee
ENV LANG=C.UTF-8 FLOOD_VERSION=${FLOOD_VERSION} RTORRENT_VERSION=0.16.23
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl gosu nginx supervisor python3 apache2-utils argon2 \
    mediainfo 7zip unzip libcurl4t64 libssl3t64 libncursesw6 libsigc++-3.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 1000 flood && useradd -u 1000 -g 1000 -m -s /usr/sbin/nologin flood \
    && groupadd rtorrent-socket && usermod -aG rtorrent-socket flood \
    && mkdir -p /etc/rtorrent /etc/supervisor/conf.d /var/log/supervisor \
    && curl -fsSL -o /usr/local/bin/flood "https://github.com/jesec/flood/releases/download/v${FLOOD_VERSION}/flood-linux-x64" \
    && echo "${FLOOD_SHA256}  /usr/local/bin/flood" | sha256sum -c - \
    && chmod 755 /usr/local/bin/flood
COPY --from=rtorrent-build /usr/local/bin/rtorrent /usr/local/bin/rtorrent
COPY --from=rtorrent-build /usr/local/lib/libtorrent.so* /usr/local/lib/
COPY sources/.rtorrent.rc /sources/.rtorrent.rc
COPY sources/nginx.conf /etc/nginx/nginx.conf
COPY sources/nginx-site.conf /etc/nginx/sites-enabled/default
COPY sources/supervisord.conf /etc/supervisord.conf
COPY sources/services.conf /etc/supervisor/conf.d/flood.conf
COPY scripts/start.sh scripts/rtcheck.py scripts/healthcheck.py scripts/callback.py scripts/bootstrap.py scripts/reset-password.py /scripts/
COPY moduser.sh /moduser.sh
RUN ldconfig && chmod 755 /scripts/* /moduser.sh \
    && flood --version && rtorrent -h | head -1
EXPOSE 80
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s CMD /scripts/healthcheck.py
CMD ["/scripts/start.sh"]
