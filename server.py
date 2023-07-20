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
import requests
#from json import load

app = Flask(__name__)

tenant_handler = TenantHandler(app.logger)

'''
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
'''
class ElevationDataSet():
    ''' this class gets and handels elevations by requests'''
    def __init__(self, name, type, dataset, elevation_mode):
        self.type = type
        self.name = name
        self.dataset = dataset
        self.elevation_mode = elevation_mode
        self.elevation = None
        self.elevations = []
        self.error = None

    def load_dataset(self, tenant):
        raster = gdal.Open(self.dataset)
        if not raster:
            self.error = 'Failed to open dataset'
            return

        gtrans = raster.GetGeoTransform()
        if not gtrans:
            self.error = 'Failed to read dataset geotransform'
            return

        rasterSpatialRef = osr.SpatialReference()
        if rasterSpatialRef.ImportFromWkt(raster.GetProjectionRef()) != 0:
            self.error = 'Failed to parse dataset projection'
            return

        band = raster.GetRasterBand(1)
        if not band:
            self.error = 'Failed to open dataset raster band'
            return

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

    def get_height(self, tenant, pos, epsg):
        dataset = self.load_dataset(tenant)
        inputSpatialRef = osr.SpatialReference()
        if inputSpatialRef.ImportFromEPSG(epsg) != 0:
            self.error = "Failed to parse projection"
            return

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
            self.error = 'Location out of bound or read data from dataset failed'
            return
        else:
            values = struct.unpack('d' * 4, data)
            kRow = row - math.floor( row );
            kCol = col - math.floor( col );
            value = ( values[0] * ( 1. - kCol ) + values[1] * kCol ) * ( 1. - kRow ) + ( values[2] * ( 1. - kCol ) + values[3] * kCol ) * ( kRow )

            if value != dataset["noDataValue"]:
                self.elevation = value * dataset["unitsToMeters"]
                return
            else:
                self.error = 'no height on this location'
                return

    def get_profile(self, tenant, query, epsg):
        dataset = self.load_dataset(tenant)
        inputSpatialRef = osr.SpatialReference()
        if inputSpatialRef.ImportFromEPSG(epsg) != 0:
            self.error = "Failed to parse projection"
            return
        crsTransform = osr.CoordinateTransformation(inputSpatialRef, dataset["spatialRef"])
        gtrans = dataset["geoTransform"]


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
                self.elevations.append(0.)
            else:
                values = struct.unpack('d' * 4, data)
                kRow = row - math.floor( row );
                kCol = col - math.floor( col );
                value = ( values[0] * ( 1. - kCol ) + values[1] * kCol ) * ( 1. - kRow ) + ( values[2] * ( 1. - kCol ) + values[3] * kCol ) * ( kRow )

                if value != dataset["noDataValue"]:
                    self.elevations.append(value * dataset["unitsToMeters"])
                else:
                    self.elevations.append(0.)

            x += totDistance / (numSamples - 1)

       # return jsonify({"elevations": elevations})

class ElevationDataSetAPI(ElevationDataSet):
    def __init__(self, name, type, dataset, elevation_mode):
        super().__init__(name, type, dataset, elevation_mode)

    def get_height(self, tenant, pos, epsg):
        try:
            api_call = self.dataset + '/height?easting=' + str(pos[0]) + '&northing=' + str(pos[1]) + '&sr=' + str(epsg)
            api_request = get(api_call)
            if api_request.status_code == 200:
                try: self.elevation = float(re.findall(r'[\d\.\d]+', api_request.text)[0])
                except: self.error = "Invalid elevation response"
            elif api_request.status_code:
                self.error = api_request.reason + ": " + api_request.text
            else: api_request.raise_for_status()
        except:
            self.error =  api_request.reason or "Invalid request"

    def get_profile(self, tenant, query, epsg):
        api_call = self.dataset+'/profile.json?geom={"type": "LineString", "coordinates":'+str(query["coordinates"])+'}&sr='+str(epsg)+'&nb_points='+str(query["samples"])
        print(api_call)
        '''
        import urllib
        print urllib.urlencode(dict(bla='Ã'))
        '''
        try:
            api_response = get(api_call)
            if api_response.status_code == 200:
                for h in api_response.json(): self.elevations.append(h["alts"]["COMB"])
            elif api_response.status_code:
                self.error = api_response.reason + ": " + api_response.text
            else: api_response.raise_for_status()
        except:
            self.error =  api_response.reason or "Invalid request"
            print(self.error)

def get_dataset(tenant):
    if 'datasets' not in g:
        g.datasets = {}
    if tenant not in g.datasets:
        dataset = initial(tenant)
        g.datasets[tenant] = dataset
    return g.datasets[tenant]

def initial(tenant):
    config_handler = RuntimeConfig("elevation", app.logger)
    config = config_handler.tenant_config(tenant)
    elevation_datasets = []
    if config.get('elevation_datasets'):
        for ds in config.get('elevation_datasets', []):
            initdata = ds['name'],ds['type'],ds['dataset'],config.get('elevation_mode')
            if ds['type'] == 'swisstopo-api':
                elevation_datasets.append(ElevationDataSetAPI(ds['name'],ds['type'],ds['dataset'],config.get('elevation_mode')))
            else:
                elevation_datasets.append(ElevationDataSet(ds['name'],ds['type'],ds['dataset'],config.get('elevation_mode')))
    elif config.get('elevation_dataset'):
        elevation_datasets.append(ElevationDataSet('elevation_dataset', 'local', config.get('elevation_dataset'), config.get('elevation_mode')))
    else:
        abort(Response('elevation_dataset(s) undefined', 500))
    return (elevation_datasets)

@app.route("/getelevation", methods=['GET'])
# `/getelevation?pos=<pos>&crs=<crs>`
# pos: the query position, as `x,y`
# crs: the crs of the query position
# output: a json document with the elevation in meters: `{elevation: h}`
def getelevation():
    tenant = tenant_handler.tenant()
    datasets = get_dataset(tenant)
    try:
        pos = request.args['pos'].split(',')
        pos = [float(pos[0]), float(pos[1])]
    except:
        return jsonify({"error": "Invalid position specified"})
    try:
        epsg = int(re.match(r'epsg:(\d+)', request.args['crs'], re.IGNORECASE).group(1))
    except:
        return jsonify({"error": "Invalid projection specified"})
    results = {}
    success = False
    error = ""
    for dataset in datasets:
        dataset.get_height(tenant, pos, epsg)
        results.update({dataset.name: {'elevation': dataset.elevation, 'error': dataset.error}})
        if dataset.elevation: success = True
        else: error = error + dataset.name + ': ' + dataset.error +"; "
    if success == False: abort(Response(error, 500))

    if datasets[0].elevation_mode== 'multi':
        return jsonify(results)
    else:
        for result in results.values():
            if result['elevation']:
                if result['elevation'] > 0:
                    answer = {'elevation': result['elevation']}
                    break
                else: answer = {'elevation': result['elevation']}
            else: answer = {'error': result['error']}
        return jsonify(answer)

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
    tenant = tenant_handler.tenant()
    datasets = get_dataset(tenant)
    query = request.json
    if not isinstance(query, dict) or not "projection" in query or not "coordinates" in query or not "distances" in query or not "samples" in query:
        return jsonify({"error": "Bad query"})

    if not isinstance(query["coordinates"], list) or len(query["coordinates"]) < 2:
        return jsonify({"error": "Insufficient number of coordinates specified"})

    if not isinstance(query["distances"], list) or len(query["distances"]) != len(query["coordinates"]) - 1:
        return jsonify({"error": "Invalid distances specified"})

    try: epsg = int(re.match(r'epsg:(\d+)', query["projection"], re.IGNORECASE).group(1))
    except: return jsonify({"error": "Invalid projection specified"})

    try: numSamples = int(query["samples"])
    except: return jsonify({"error": "Invalid sample count specified"})

    inputSpatialRef = osr.SpatialReference()
    if inputSpatialRef.ImportFromEPSG(epsg) != 0:
        return jsonify({"error": "Failed to parse projection"})
    answer = {}
    test = {}
    success = False
    errormsg = ""
    suffix = ""
    i = 0
    for dataset in datasets:
        dataset.get_profile(tenant, query, epsg)
        answer.update({"elevations"+suffix: dataset.elevations})
        i += 1
        suffix = "_"+str(i)
        if dataset.elevations: success = True
        else: errormsg = errormsg + dataset.name + ': ' + dataset.error +"; "
    if success == False: abort(Response(errormsg, 500))
    else: return jsonify(answer)

'''
    dataset = get_dataset(tenant_handler.tenant())
    query = request.json



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
'''

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
