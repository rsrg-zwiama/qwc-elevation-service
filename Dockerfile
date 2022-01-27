FROM sourcepole/qwc-uwsgi-base:ubuntu-v2022.01.26

ADD . /srv/qwc_service

RUN \
    apt-get update && \
    apt-get install -y python3-gdal && \
    pip3 install --no-cache-dir -r /srv/qwc_service/requirements.txt && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ENV SERVICE_MOUNTPOINT=/elevation
