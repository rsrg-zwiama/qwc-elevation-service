FROM sourcepole/qwc-uwsgi-base:alpine-v2023.10.26

ADD requirements.txt /srv/qwc_service/requirements.txt

RUN \
    apk add --no-cache --update --virtual runtime-deps py3-gdal && \
    pip3 install --no-cache-dir -r /srv/qwc_service/requirements.txt

ADD src /srv/qwc_service/

ENV SERVICE_MOUNTPOINT=/elevation
