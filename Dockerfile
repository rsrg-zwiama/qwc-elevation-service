FROM sourcepole/qwc-uwsgi-base:ubuntu-latest

RUN apt-get update && apt-get install -y python3-gdal

ADD . /srv/qwc_service
RUN pip3 install --no-cache-dir -r /srv/qwc_service/requirements.txt

ENV SERVICE_MOUNTPOINT=/elevation
ENV ELEVATION_DATASET=/vsicurl/https://data.sourcepole.com/srtm_1km_3857.tif
