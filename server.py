#!/usr/bin/python
# Copyright 2018, Sourcepole AG
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from flask import Flask, g, abort, request, Response, jsonify, make_response
from itertools import accumulate
from osgeo import gdal
from osgeo import ogr
from osgeo import osr
import math
import re
import struct
import sys
from qwc_services_core.tenant_handler import TenantHandler
from qwc_services_core.runtime_config import RuntimeConfig

from requests import get
#from json import load

app = Flask(__name__)

tenant_handler = TenantHandler(app.logger)

def get_dataset(tenant):
    if 'datasets' not in g:
        g.datasets = {}
    if tenant not in g.datasets:
        dataset = load_dataset(tenant)
        g.datasets[tenant] = dataset
    return g.datasets[tenant]


def load_dataset(tenant):
    config_handler = RuntimeConfig("elevation", app.logger)
    config = config_handler.tenant_config(tenant)

    dsfn = config.get('elevation_dataset')
    if dsfn is None:
        abort(Response('elevation_dataset undefined', 500))

    raster = gdal.Open(dsfn)
    if not raster:
        abort(Response('Failed to open dataset', 500))

    gtrans = raster.GetGeoTransform()
    if not gtrans:
        abort(Response('Failed to read dataset geotransform', 500))

    rasterSpatialRef = osr.SpatialReference()
    if rasterSpatialRef.ImportFromWkt(raster.GetProjectionRef()) != 0:
        abort(Response('Failed to parse dataset projection', 500))

    band = raster.GetRasterBand(1)
    if not band:
        abort(Response('Failed to open dataset raster band', 500))

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

class ElevationDataSet():
    ''' this class gets and handels elevations by requests'''
    def __init__(self, name, type, dataset, elevation_mode):
        self.type = type
        self.name = name
        self.dataset = dataset
        self.elevation_mode = elevation_mode
        self.elevation = None
        self.error = None
    def get_dataset(self, tenant):
        return {"error": "1"}

    def load_dataset(self, tenant, pos, epsg):
        return {"error": "2"}

class ElevationDataSetAPI(ElevationDataSet):
    def __init__(self, name, type, dataset, elevation_mode):
        super().__init__(name, type, dataset, elevation_mode)

    def get_dataset(self):
        if self.dataset is None:
            return (abort(Response('elevation_api undefined', 500)))
        else:

            return(self.dataset)

    def load_dataset(self, tenant, pos, epsg):
        if self.dataset is None:
            return (abort(Response('elevation_api undefined', 500)))
        else:
            try:
                api_call = self.dataset + '?easting=' + str(pos[0]) + '&northing=' + str(pos[1]) + '&sr=' + str(epsg)
                api_request = get(api_call)
            except:
                self.error = {"error": "Invalid request"}
        if api_request.status_code == 200:
            try:
                self.elevation = re.findall(r'[\d\.\d]+', api_request.text)
                self.elevation = float(self.elevation[0])
            except:
                self.error = {"error": "Invalid elevation response"}
                self.elevation = 0
        else:
            self.error = {"error": raise_for_status(api_request.status_code)}


def initial(tenant):
    config_handler = RuntimeConfig("elevation", app.logger)
    config = config_handler.tenant_config(tenant)
    elevation_datasets = []
    if config.get('elevation_datasets'):
        for ds in config.get('elevation_datasets', []):
            initdata = ds['name'],ds['type'],ds['dataset'],config.get('elevation_mode')
            if ds['type'] == 'swisstopo-api': elevation_datasets.append(ElevationDataSetAPI(initdata)
                resource = ElevationDataSetAPI(ds['name'],ds['type'],ds['dataset'],config.get('elevation_mode'))
                elevation_datasets.append(resource)
            else:
                resource = ElevationDataSet(ds['name'],ds['type'], ds['dataset'], config.get('elevation_mode'))
                elevation_datasets.append(resource)
    else:
        elevation_datasets.append(ElevationDataSet('elevation_dataset', 'local', config.get('elevation_dataset'), config.get('elevation_mode')))
    return (elevation_datasets)

@app.route("/getelevation", methods=['GET'])
# `/getelevation?pos=<pos>&crs=<crs>`
# pos: the query position, as `x,y`
# crs: the crs of the query position
# output: a json document with the elevation in meters: `{elevation: h}`
def getelevation():
    tenant = tenant_handler.tenant()
    elevation_datasets = initial(tenant)
    try:
        pos = request.args['pos'].split(',')
        pos = [float(pos[0]), float(pos[1])]
    except:
        return jsonify({"error": "Invalid position specified"})
    try:
        epsg = int(re.match(r'epsg:(\d+)', request.args['crs'], re.IGNORECASE).group(1))
    except:
        return jsonify({"error": "Invalid projection specified"})
    result = {}
    for elevation_dataset in elevation_datasets:
        elevation_dataset.load_dataset(tenant, pos, epsg)
        result.update({elevation_dataset.name: elevation_dataset.elevation})

    if elevation_datasets [0].elevation_mode== 'multi':

        return jsonify(result)
    else:
        for value in result.values():
            if value:
                if value > 0:
                    elevation = value
                    break
                else:
                    elevation = value
            else:
                elevation = elevation_datasets[0].elevation
        return jsonify({'elevation': elevation})


"""
    inputSpatialRef = osr.SpatialReference()
    if inputSpatialRef.ImportFromEPSG(epsg) != 0:
        return jsonify({"error": "Failed to parse projection"})

    crsTransform = osr.CoordinateTransformation(inputSpatialRef, dataset["spatialRef"])
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
        return jsonify({"elevation": 0})
    else:
        values = struct.unpack('d' * 4, data)
        kRow = row - math.floor( row );
        kCol = col - math.floor( col );
        value = ( values[0] * ( 1. - kCol ) + values[1] * kCol ) * ( 1. - kRow ) + ( values[2] * ( 1. - kCol ) + values[3] * kCol ) * ( kRow )

        if value != dataset["noDataValue"]:
            return jsonify({"elevation": value * dataset["unitsToMeters"]})
        else:
            return jsonify({"elevation": 0})
"""

@app.route("/getheightprofile", methods=['POST'])
# `/getheightprofile`
# payload: a json document as follows:
#        {
#            coordinates: [[x1,y1],[x2,y2],...],
#            distances: [<dist_x1_x2>, <dist_x2_x3>, ...],
#            projection: <EPSG:XXXX, projection of coordinates>,
#            samples: <number of height samples to return>
#        }
# output: a json document with heights in meters: `{elevations: [h1, h2, ...]}`
def getheightprofile():
    dataset = get_dataset(tenant_handler.tenant())
    query = request.json

    if not isinstance(query, dict) or not "projection" in query or not "coordinates" in query or not "distances" in query or not "samples" in query:
        return jsonify({"error": "Bad query"})

    if not isinstance(query["coordinates"], list) or len(query["coordinates"]) < 2:
        return jsonify({"error": "Insufficient number of coordinates specified"})

    if not isinstance(query["distances"], list) or len(query["distances"]) != len(query["coordinates"]) - 1:
        return jsonify({"error": "Invalid distances specified"})

    try:
        epsg = int(re.match(r'epsg:(\d+)', query["projection"], re.IGNORECASE).group(1))
    except:
        return jsonify({"error": "Invalid projection specified"})

    try:
        numSamples = int(query["samples"])
    except:
        return jsonify({"error": "Invalid sample count specified"})

    inputSpatialRef = osr.SpatialReference()
    if inputSpatialRef.ImportFromEPSG(epsg) != 0:
        return jsonify({"error": "Failed to parse projection"})

    crsTransform = osr.CoordinateTransformation(inputSpatialRef, dataset["spatialRef"])
    gtrans = dataset["geoTransform"]

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

        pRaster = crsTransform.TransformPoint(p1[0] + mu * dr[0], p1[1] + mu * dr[1])

        # Geographic coordinates to pixel coordinates
        col = ( -gtrans[0] * gtrans[5] + gtrans[2] * gtrans[3] - gtrans[2] * pRaster[1] + gtrans[5] * pRaster[0] ) / ( gtrans[1] * gtrans[5] - gtrans[2] * gtrans[4] )
        row = ( -gtrans[0] * gtrans[4] + gtrans[1] * gtrans[3] - gtrans[1] * pRaster[1] + gtrans[4] * pRaster[0] ) / ( gtrans[2] * gtrans[4] - gtrans[1] * gtrans[5] )

        if math.floor(col) > 0 and math.floor(col) < dataset["raster"].RasterXSize - 1 and math.floor(row) > 0 and math.floor(row) < dataset["raster"].RasterYSize - 1:
            data = dataset["band"].ReadRaster(math.floor(col), math.floor(row), 2, 2, 2, 2, gdal.GDT_Float64)
        else:
            data = None

        if not data or len(data) != 32:
            elevations.append(0.)
        else:
            values = struct.unpack('d' * 4, data)
            kRow = row - math.floor( row );
            kCol = col - math.floor( col );
            value = ( values[0] * ( 1. - kCol ) + values[1] * kCol ) * ( 1. - kRow ) + ( values[2] * ( 1. - kCol ) + values[3] * kCol ) * ( kRow )

            if value != dataset["noDataValue"]:
                elevations.append(value * dataset["unitsToMeters"])
            else:
                elevations.append(0.)

        x += totDistance / (numSamples - 1)

    return jsonify({"elevations": elevations})


""" readyness probe endpoint """
@app.route("/ready", methods=['GET'])
def ready():
    return jsonify({"status": "OK"})


""" liveness probe endpoint """
@app.route("/healthz", methods=['GET'])
def healthz():
    dataset = get_dataset(tenant_handler.tenant())
    if dataset is None:
        return make_response(jsonify({
            "status": "FAIL", "cause": "Failed to open elevation_dataset"}), 500)

    return jsonify({"status": "OK"})


if __name__ == "__main__":
    from flask_cors import CORS
    CORS(app)
    app.run(host='localhost', port=5002, debug=True)
