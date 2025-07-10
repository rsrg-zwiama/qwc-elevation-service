[![](https://github.com/qwc-services/qwc-elevation-service/workflows/build/badge.svg)](https://github.com/qwc-services/qwc-elevation-service/actions)
[![docker](https://img.shields.io/docker/v/sourcepole/qwc-elevation-service?label=Docker%20image&sort=semver)](https://hub.docker.com/r/sourcepole/qwc-elevation-service)

QWC Elevation Service
=====================

Returns elevations.


Configuration
-------------

The static config files are stored as JSON files in `$CONFIG_PATH` with subdirectories for each tenant,
e.g. `$CONFIG_PATH/default/*.json`. The default tenant name is `default`.

### Elevation Service config

* [JSON schema](schemas/qwc-elevation-service.json)
* File location: `$CONFIG_PATH/<tenant>/elevationConfig.json`

Example:
```json
{
  "$schema": "https://raw.githubusercontent.com/qwc-services/qwc-elevation-service/master/schemas/qwc-elevation-service.json",
  "service": "elevation",
  "config": {
    "elevation_dataset": "/vsicurl/https://data.sourcepole.com/srtm_1km_3857.tif"
  }
}
```

### Environment variables

Config options in the config file can be overridden by equivalent uppercase environment variables.

| Variable                | Description            |
|-------------------------|------------------------|
| ELEVATION_DATASET       | path/to/dtm.tif        |


Usage
-----

Install GDAL Python bindings. `python-gdal` or `python3-gdal` packages on Debian/Ubuntu.

Run with uv:

    uv venv --system-site-packages
    ELEVATION_DATASET=/vsicurl/https://data.sourcepole.com/srtm_1km_3857.tif uv run src/server.py

API:
* Runs by default on `http://localhost:5002`
* `GET: /getelevation?pos=<pos>&crs=<crs>`
  - *pos*: the query position, as `x,y`
  - *crs*: the crs of the query position
  - *output*: a json document with the elevation in meters: `{elevation: h}`
  - Example: http://localhost:5002/getelevation?pos=45.976,7.658&crs=EPSG:4326
* `POST: /getheightprofile`
  - *payload*: a json document as follows:

        {
            coordinates: [[x1,y1],[x2,y2],...],
            distances: [<dist_p1_p2>, <dist_p2_p3>, ...],
            projection: <EPSG:XXXX, projection of coordinates>,
            samples: <number of height samples to return>
        }

  - *output*: a json document with heights in meters: `{elevations: [h1, h2, ...]}`


Docker usage
------------

See sample [docker-compose.yml](https://github.com/qwc-services/qwc-docker/blob/master/docker-compose-example.yml) of [qwc-docker](https://github.com/qwc-services/qwc-docker).

