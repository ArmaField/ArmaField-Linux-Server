# syntax=docker/dockerfile:1
FROM debian:bookworm-slim

LABEL org.opencontainers.image.source="https://github.com/ArmaField/ArmaField-Linux-Server"
LABEL org.opencontainers.image.description="ArmaField Linux Dedicated Server"
LABEL org.opencontainers.image.licenses="MIT"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        lib32gcc-s1 \
        lib32stdc++6 \
        libcurl4 \
        libssl3 \
        ca-certificates \
        wget \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /steamcmd \
    && wget -qO- 'https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz' \
        | tar zxf - -C /steamcmd

ENV STEAM_APPID=1874900 \
    ARMA_BINARY=./ArmaReforgerServer \
    ARMA_PROFILE=/profile \
    ARMA_WORKSHOP_DIR=/workshop \
    RUNTIME_CONFIG=/tmp/runtime_config.json

WORKDIR /reforger

COPY launch.py /launch.py

STOPSIGNAL SIGINT

CMD ["python3", "-u", "/launch.py"]