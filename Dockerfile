FROM sourcepole/qwc-uwsgi-base:ubuntu-v2021.12.16

RUN apt-get update && apt-get install -y python3-gdal

ADD . /srv/qwc_service
RUN pip3 install --no-cache-dir -r /srv/qwc_service/requirements.txt

ENV SERVICE_MOUNTPOINT=/elevation
