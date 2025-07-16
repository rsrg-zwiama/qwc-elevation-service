#!/usr/bin/python
# Copyright 2018, Sourcepole AG
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from flask import Flask, g, abort, request, make_response
from itertools import accumulate
from osgeo import gdal
from osgeo import osr
import math
import re
import struct
from qwc_services_core.tenant_handler import (
    TenantHandler, TenantPrefixMiddleware, TenantSessionInterface)
from qwc_services_core.runtime_config import RuntimeConfig

app = Flask(__name__)

tenant_handler = TenantHandler(app.logger)
app.wsgi_app = TenantPrefixMiddleware(app.wsgi_app)
app.session_interface = TenantSessionInterface()


def get_datasets(tenant):
    if 'datasets' not in g:
        g.datasets = {}
    if tenant not in g.datasets:
        datasets = load_datasets(tenant)
        g.datasets[tenant] = datasets
    return g.datasets[tenant]


def load_single_dataset(dataset_filename):
    raster = gdal.Open(dataset_filename)
    if not raster:
        abort(make_response('Failed to open dataset', 500))

    gtrans = raster.GetGeoTransform()
    if not gtrans:
        abort(make_response('Failed to read dataset geotransform', 500))

    rasterSpatialRef = osr.SpatialReference()
    if rasterSpatialRef.ImportFromWkt(raster.GetProjectionRef()) != 0:
        abort(make_response('Failed to parse dataset projection', 500))

    band = raster.GetRasterBand(1)
    if not band:
        abort(make_response('Failed to open dataset raster band', 500))

    rasterUnitsToMeters = 1
    if band.GetUnitType() == "ft":
        rasterUnitsToMeters = 0.3048

    noDataValue = band.GetNoDataValue()
    if not noDataValue:
      noDataValue = None

    dataset = {
        "raster": raster,
        "band": band,
        "spatialRef": rasterSpatialRef,
        "geoTransform": gtrans,
        "unitsToMeters": rasterUnitsToMeters,
        "noDataValue": noDataValue
    }
    return dataset


def load_datasets(tenant):
    config_handler = RuntimeConfig("elevation", app.logger)
    config = config_handler.tenant_config(tenant)

    single_dataset = config.get('elevation_dataset')
    datasets_config = config.get('elevation_datasets', [])

    if (
        (not datasets_config or not isinstance(datasets_config, list) or len(datasets_config) == 0)
        and not single_dataset
    ):
        abort(make_response('elevation_datasets and elevation_dataset config parameters are undefined', 500))

    if single_dataset:
        datasets_config.insert(0, {
            "name": None,
            "dataset_path": single_dataset
        })

    datasets = [
        (
            cfg.get("name", None),
            load_single_dataset(cfg["dataset_path"])
        )
        for cfg in datasets_config
    ]
    return datasets


def sample_elevation(dataset, pos, crsTransform):
    gtrans = dataset["geoTransform"]

    pRaster = crsTransform.TransformPoint(pos[0], pos[1])

    # Geographic coordinates to pixel coordinates
    col = ( -gtrans[0] * gtrans[5] + gtrans[2] * gtrans[3] - gtrans[2] * pRaster[1] + gtrans[5] * pRaster[0] ) / ( gtrans[1] * gtrans[5] - gtrans[2] * gtrans[4] )
    row = ( -gtrans[0] * gtrans[4] + gtrans[1] * gtrans[3] - gtrans[1] * pRaster[1] + gtrans[4] * pRaster[0] ) / ( gtrans[2] * gtrans[4] - gtrans[1] * gtrans[5] )

    if math.floor(col) > 0 and math.floor(col) < dataset["raster"].RasterXSize - 1 and math.floor(row) > 0 and math.floor(row) < dataset["raster"].RasterYSize - 1:
        data = dataset["band"].ReadRaster(math.floor(col), math.floor(row), 2, 2, 2, 2, gdal.GDT_Float64)
    else:
        data = None

    if not data or len(data) != 32:
        return 0
    else:
        values = struct.unpack('d' * 4, data)
        kRow = row - math.floor( row );
        kCol = col - math.floor( col );
        value = ( values[0] * ( 1. - kCol ) + values[1] * kCol ) * ( 1. - kRow ) + ( values[2] * ( 1. - kCol ) + values[3] * kCol ) * ( kRow )

        if value != dataset["noDataValue"]:
            return value * dataset["unitsToMeters"]
        else:
            return 0


@app.route("/getelevation", methods=['GET'])
# `/getelevation?pos=<pos>&crs=<crs>`
# pos: the query position, as `x,y`
# crs: the crs of the query position
# output: a json document with the elevation in meters: `{elevation: h}`
#   or a list of elevations for each dataset:
#   `{elevation_list: [{dataset: dataset1, elevation: h}, {dataset: dataset2, elevation: h}, ...]}`
def getelevation():
    datasets = get_datasets(tenant_handler.tenant())
    try:
        pos = request.args['pos'].split(',')
        pos = [float(pos[0]), float(pos[1])]
    except:
        return {"error": "Invalid position specified"}, 400
    try:
        epsg = int(re.match(r'epsg:(\d+)', request.args['crs'], re.IGNORECASE).group(1))
    except:
        return {"error": "Invalid projection specified"}, 400

    inputSpatialRef = osr.SpatialReference()
    if inputSpatialRef.ImportFromEPSG(epsg) != 0:
        return {"error": "Failed to parse projection"}, 400


    elevations = []
    for (name, dataset) in datasets:
        crsTransform = osr.CoordinateTransformation(inputSpatialRef, dataset["spatialRef"])
        elevation = sample_elevation(dataset, pos, crsTransform)

        elevations.append({
            "dataset": name,
            "elevation": elevation
        })

    # Backwards compatibility for single dataset
    if len(elevations) == 1 and elevations[0]["dataset"] is None:
        return {"elevation": elevations[0]["elevation"]}
    return {"elevation_list": elevations}


@app.route("/getheightprofile", methods=['POST'])
# `/getheightprofile`
# payload: a json document as follows:
#        {
#            coordinates: [[x1,y1],[x2,y2],...],
#            distances: [<dist_x1_x2>, <dist_x2_x3>, ...],
#            projection: <EPSG:XXXX, projection of coordinates>,
#            samples: <number of height samples to return>
#        }
# output: a json document with either heights in meters: `{elevations: [h1, h2, ...]}`
#   or a list of elevations for each dataset:
#  `{elevations_list: [{dataset: dataset1, elevations: [h1, h2, ...]}, {dataset: dataset2, elevations: [h1, h2, ...]}, ...]}`
def getheightprofile():
    datasets = get_datasets(tenant_handler.tenant())
    query = request.json

    if not isinstance(query, dict) or not "projection" in query or not "coordinates" in query or not "distances" in query or not "samples" in query:
        return {"error": "Bad query"}, 400

    if not isinstance(query["coordinates"], list) or len(query["coordinates"]) < 2:
        return {"error": "Insufficient number of coordinates specified"}, 400

    if not isinstance(query["distances"], list) or len(query["distances"]) != len(query["coordinates"]) - 1:
        return {"error": "Invalid distances specified"}, 400

    try:
        epsg = int(re.match(r'epsg:(\d+)', query["projection"], re.IGNORECASE).group(1))
    except:
        return {"error": "Invalid projection specified"}, 400

    try:
        numSamples = int(query["samples"])
    except:
        return {"error": "Invalid sample count specified"}, 400

    inputSpatialRef = osr.SpatialReference()
    if inputSpatialRef.ImportFromEPSG(epsg) != 0:
        return {"error": "Failed to parse projection"}, 400

    datasets_elevations = []

    for (name, dataset) in datasets:
        crsTransform = osr.CoordinateTransformation(inputSpatialRef, dataset["spatialRef"])

        elevations = []

        x = 0
        i = 0
        p1 = query["coordinates"][i]
        p2 = query["coordinates"][i + 1]
        dr = (p2[0] - p1[0], p2[1] - p1[1])
        cumDistances = list(accumulate(query["distances"]))
        cumDistances.insert(0, 0)
        totDistance = sum(query["distances"])
        for s in range(0, numSamples):
            while i + 2 < len(cumDistances) and x > cumDistances[i + 1]:
                i += 1
                p1 = query["coordinates"][i]
                p2 = query["coordinates"][i + 1]
                dr = (p2[0] - p1[0], p2[1] - p1[1])

            try:
                mu = (x - cumDistances[i]) / (cumDistances[i+1] - cumDistances[i])
            except ZeroDivisionError:
                mu = 0

            pos = (p1[0] + mu * dr[0], p1[1] + mu * dr[1])

            elevation = sample_elevation(dataset, pos, crsTransform)
            elevations.append(elevation)

            x += totDistance / (numSamples - 1)

        datasets_elevations.append({
            "dataset": name,
            "elevations": elevations
        })

    # Backwards compatibility for single dataset
    if len(datasets_elevations) == 1 and datasets_elevations[0]["dataset"] is None:
        return {"elevations": datasets_elevations[0]["elevations"]}

    return {"elevations_list": datasets_elevations}


""" readyness probe endpoint """
@app.route("/ready", methods=['GET'])
def ready():
    return {"status": "OK"}


""" liveness probe endpoint """
@app.route("/healthz", methods=['GET'])
def healthz():
    dataset = get_datasets(tenant_handler.tenant())
    if dataset is None:
        return {"status": "FAIL", "cause": "Failed to open elevation_dataset"}, 500

    return {"status": "OK"}


if __name__ == "__main__":
    from flask_cors import CORS
    CORS(app)
    app.run(host='localhost', port=5002, debug=True)
