FROM alpine:3.7

ENV FLOOD_VER=1.0.0
ARG RTORRENT_VERSION=0.9.6
ARG LIBTORRENT_VERSION=0.13.6
ARG XMLRPC_VERSION=01.51.00
ARG LIBSIG_VERSION=2.10.0
ARG CARES_VERSION=1.13.0
ARG CURL_VERSION=7.55.1

RUN \
    addgroup -S flood -g 1000 && \
    adduser -D -S -h /home/flood -s /sbin/nologin -G flood flood -u 1000 && \
    apk add --no-cache \
    supervisor \
    ca-certificates \
    bash \
    coreutils \
    libcap \
    mediainfo

RUN NB_CORES=${BUILD_CORES-`getconf _NPROCESSORS_CONF`} && apk add --no-cache -t build-dependencies \
    build-base \
    git \
    libtool \
    automake \
    autoconf \
    wget \
    tar \
    xz \
    zlib-dev \
    cppunit-dev \
    libressl-dev \
    ncurses-dev \
    curl-dev \
    binutils

RUN apk add -X http://dl-cdn.alpinelinux.org/alpine/v3.6/main -U cppunit-dev==1.13.2-r1 cppunit==1.13.2-r1
RUN cd /tmp && \
    git clone https://github.com/mirror/xmlrpc-c.git && \
    cd xmlrpc-c/stable && ./configure && make -j ${NB_CORES} && make install && \
    cd /tmp && wget http://ftp.gnome.org/pub/GNOME/sources/libsigc++/2.10/libsigc++-${LIBSIG_VERSION}.tar.xz && \
    unxz libsigc++-${LIBSIG_VERSION}.tar.xz && tar -xf libsigc++-${LIBSIG_VERSION}.tar && \
    cd libsigc++-${LIBSIG_VERSION} && ./configure && make -j ${NB_CORES} && make install && \
    cd /tmp && wget https://c-ares.haxx.se/download/c-ares-${CARES_VERSION}.tar.gz && \
    tar zxf c-ares-${CARES_VERSION}.tar.gz && \
    cd c-ares-${CARES_VERSION} && ./configure && make -j ${NB_CORES} && make install && \
    cd /tmp && wget https://curl.haxx.se/download/curl-${CURL_VERSION}.tar.gz && \
    tar zxf curl-${CURL_VERSION}.tar.gz && \
    cd curl-${CURL_VERSION}  && ./configure --enable-ares --enable-tls-srp --enable-gnu-tls --with-ssl --with-zlib && make && make install && \
    cd /tmp && git clone https://github.com/rakshasa/libtorrent.git && cd libtorrent && git checkout tags/${LIBTORRENT_VERSION} && \
    ./autogen.sh && ./configure --with-posix-fallocate && make -j ${NB_CORES} && make install && \
    cd /tmp && git clone https://github.com/rakshasa/rtorrent.git && cd rtorrent && git checkout tags/${RTORRENT_VERSION} && \
    ./autogen.sh && ./configure --with-xmlrpc-c --with-ncurses && make -j ${NB_CORES} && make install

RUN apk add --no-cache \
    --repository http://dl-cdn.alpinelinux.org/alpine/v3.7/main \
    python \
    nodejs \
    nodejs-npm && \
    mkdir /usr/flood && \
    cd /usr/flood && \
    wget -qO- https://github.com/jfurrow/flood/archive/v${FLOOD_VER}.tar.gz | tar xz --strip 1 && \
    npm install --production

RUN apk del build-dependencies && rm -rf /tmp/* && \
    rm -rf /var/cache/apk/*

RUN setcap cap_net_bind_service=+ep /usr/bin/node
ADD sources /sources
ADD sources/supervisord.conf /etc/supervisord.conf
ADD scripts/start.sh /scripts/start.sh
RUN chmod -R +x /scripts

EXPOSE 80

CMD [ "/scripts/start.sh" ]