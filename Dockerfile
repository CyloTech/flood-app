FROM ubuntu
USER root

ENV LANG en_US.UTF-8
ENV RUTORRENT_VERSION master
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y git && \
    apt-get update && \
    apt-get install -y \
    tar \
    xz-utils \
    mediainfo \
    curl \
    wget \
    supervisor \
    libcap2-bin \
    nodejs \
    npm \
    software-properties-common && \
    add-apt-repository ppa:ondrej/php && \
    apt update && \
    apt install -y \
    openssl

RUN apt-get install -y lsb-release build-essential pkg-config \
    subversion git time lsof binutils tmux curl wget \
    python-setuptools python-virtualenv python-dev \
    libssl-dev zlib1g-dev libncurses-dev libncursesw5-dev \
    libcppunit-dev autoconf automake libtool \
    libffi-dev libxml2-dev libxslt1-dev
RUN adduser --system --disabled-password --home /home/flood --shell /sbin/nologin --group --uid 1000 flood
RUN /bin/su -s /bin/bash -c "cd && \
TERM=xterm git clone https://github.com/CyloTech/rtorrent-ps.git && \
cd rtorrent-ps && \
nice ./build.sh all && \
cd && \
rm -rf rtorrent-ps" flood

RUN mkdir /usr/src/app && \
    git clone https://github.com/jfurrow/flood.git /usr/src/app
ADD sources/config.js /usr/src/app/config.js
RUN cd /usr/src/app && \
    npm install -g node-gyp && \
    npm install && \
    npm cache clean --force && \
    npm run build

RUN setcap cap_net_bind_service=+ep /usr/bin/node
ADD sources /sources
ADD sources/supervisord.conf /etc/supervisord.conf
ADD scripts/start.sh /scripts/start.sh
RUN chmod -R +x /scripts

RUN apt-get remove -y lsb-release pkg-config \
    subversion time lsof \
    python-virtualenv python-dev \
    zlib1g-dev libncurses-dev libncursesw5-dev \
    libcppunit-dev libffi-dev libxml2-dev libxslt1-dev
RUN rm -rf /tmp/*
RUN apt autoremove -y && apt clean
RUN rm -rf /var/lib/apt/lists/*

EXPOSE 80

CMD [ "/scripts/start.sh" ]