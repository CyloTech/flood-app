FROM alpine:3.7

ENV FLOOD_VER=1.0.0

RUN \
    addgroup -S flood -g 1000 && \
    adduser -D -S -h /home/flood -s /sbin/nologin -G flood flood -u 1000 && \
    apk add --no-cache \
    supervisor \
    ca-certificates \
    rtorrent \
    curl \
    bash \
    coreutils \
    libcap \
    mediainfo

RUN apk add --no-cache -t build-dependencies \
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

RUN apk add --no-cache \
    --repository http://dl-cdn.alpinelinux.org/alpine/v3.7/main \
    python \
    nodejs \
    nodejs-npm && \
    mkdir /usr/flood && \
    cd /usr/flood && \
    wget -qO- https://github.com/jfurrow/flood/archive/v${FLOOD_VER}.tar.gz | tar xz --strip 1 && \
    npm install --production

RUN apk del build-dependencies

RUN setcap cap_net_bind_service=+ep /usr/bin/node
ADD sources /sources
ADD sources/supervisord.conf /etc/supervisord.conf
ADD scripts/start.sh /scripts/start.sh
RUN chmod -R +x /scripts

EXPOSE 80

CMD [ "/scripts/start.sh" ]