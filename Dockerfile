FROM sourcepole/qwc-uwsgi-base:alpine-v2022.01.26

ADD . /srv/qwc_service

RUN \
    apk add --no-cache --update --virtual runtime-deps py3-gdal && \
    pip3 install --no-cache-dir -r /srv/qwc_service/requirements.txt

ENV SERVICE_MOUNTPOINT=/elevation
