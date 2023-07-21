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

app = Flask(__name__)

tenant_handler = TenantHandler(app.logger)

class ElevationDataSet():
    ''' this class gets and handels elevations by reading datasource and is default class'''
    def __init__(self, name, type, datasource, elevation_mode):
        self.type = type
        self.name = name
        self.datasource = datasource
        self.elevation = None
        self.elevations = []
        self.error = None

    def load_dataset(self, tenant):
        '''This function opens datasource and returns dataset'''
        raster = gdal.Open(self.datasource)
        if not raster:
            self.error = 'Failed to open datasource: Source not accessible or existing'
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
        '''Function to save height to self.elevation'''
        dataset = self.load_dataset(tenant)
        if not dataset: return
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

    def get_profile(self, tenant, query, epsg, numSamples):
        '''Function to save list of heights to self.elevations'''
        dataset = self.load_dataset(tenant)
        if not dataset: return
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

            try: mu = (x - cumDistances[i]) / (cumDistances[i+1] - cumDistances[i])
            except ZeroDivisionError: mu = 0

            pRaster = crsTransform.TransformPoint(p1[0] + mu * dr[0], p1[1] + mu * dr[1])

            # Geographic coordinates to pixel coordinates
            col = ( -gtrans[0] * gtrans[5] + gtrans[2] * gtrans[3] - gtrans[2] * pRaster[1] + gtrans[5] * pRaster[0] ) / ( gtrans[1] * gtrans[5] - gtrans[2] * gtrans[4] )
            row = ( -gtrans[0] * gtrans[4] + gtrans[1] * gtrans[3] - gtrans[1] * pRaster[1] + gtrans[4] * pRaster[0] ) / ( gtrans[2] * gtrans[4] - gtrans[1] * gtrans[5] )

            if math.floor(col) > 0 and math.floor(col) < dataset["raster"].RasterXSize - 1 and math.floor(row) > 0 and math.floor(row) < dataset["raster"].RasterYSize - 1:
                data = dataset["band"].ReadRaster(math.floor(col), math.floor(row), 2, 2, 2, 2, gdal.GDT_Float64)
            else: data = None

            if not data or len(data) != 32: self.elevations.append(0.)
            else:
                values = struct.unpack('d' * 4, data)
                kRow = row - math.floor( row );
                kCol = col - math.floor( col );
                value = ( values[0] * ( 1. - kCol ) + values[1] * kCol ) * ( 1. - kRow ) + ( values[2] * ( 1. - kCol ) + values[3] * kCol ) * ( kRow )

                if value != dataset["noDataValue"]:
                    self.elevations.append(value * dataset["unitsToMeters"])
                else: self.elevations.append(0.)
            x += totDistance / (numSamples - 1)


class ElevationDataSetAPI(ElevationDataSet):
    ''' this class, child of ElevationDataSet, gets and handels elevations by requests to API'''
    def __init__(self, name, type, datasource, elevation_mode):
        super().__init__(name, type, datasource, elevation_mode)

    def get_height(self, tenant, pos, epsg):
        '''Function to save height value to self.elevation'''
        api_call = self.datasource + '/height?easting=' + str(pos[0]) + '&northing=' + str(pos[1]) + '&sr=' + str(epsg)
        try:
            api_response = get(api_call)
            if api_response.status_code == 200:
                try: self.elevation = float(re.findall(r'[\d\.\d]+', api_response.text)[0])
                except: self.error = "Invalid elevation response"
            else:
                api_response.status_code
                self.error = api_response.reason + ": " + api_response.text
        except requests.exceptions.RequestException as err:
            self.error = str(err) or "Invalid request"

    def get_profile(self, tenant, query, epsg, numSamples):
        '''Function to save list of heights to self.elevations'''
        api_call = self.datasource+'/profile.json?geom={"type": "LineString", "coordinates":'+str(query["coordinates"])+'}&sr='+str(epsg)+'&nb_points='+str(numSamples)
        try:
            api_response = get(api_call)
            if api_response.status_code == 200:
                for h in api_response.json(): self.elevations.append(h["alts"]["COMB"])
            else:
                api_response.status_code
                self.error = api_response.reason + ": " + api_response.text
        except requests.exceptions.RequestException as err:
            self.error = str(err) or "Invalid request"


def get_datasource(tenant):
    '''Function tests if data already exists in current request'''
    if 'datasources' not in g:
        g.datasources = {}
    if tenant not in g.datasources:
        datasources = initial(tenant)
        g.datasources[tenant] = datasources
    return g.datasources[tenant]

def initial(tenant):
    '''Create Instances of ElevationDataSet(API)'''
    config_handler = RuntimeConfig("elevation", app.logger)
    config = config_handler.tenant_config(tenant)
    datasources = []

    dsfn = config.get('elevation_dataset')
    if isinstance(dsfn, list):
        for ds in dsfn:
            if ds['type'] == 'swisstopo-api':
                datasources.append(ElevationDataSetAPI(ds['name'],ds['type'],ds['datasource'],config.get('elevation_mode')))
            else:
                datasources.append(ElevationDataSet(ds['name'],ds['type'],ds['datasource'],config.get('elevation_mode')))
    elif isinstance(dsfn, str):
        datasources.append(ElevationDataSet('elevation_dataset', 'local', config.get('elevation_dataset'), config.get('elevation_mode')))
    else:
        abort(Response('elevation_dataset(s) undefined', 500))
    return (datasources)

@app.route("/getelevation", methods=['GET'])
# `/getelevation?pos=<pos>&crs=<crs>`
# pos: the query position, as `x,y`
# crs: the crs of the query position
# output: a json document with the elevation in meters: `{elevation: h}`
def getelevation():
    tenant = tenant_handler.tenant()
    datasources = get_datasource(tenant)
    try:
        pos = request.args['pos'].split(',')
        pos = [float(pos[0]), float(pos[1])]
    except:
        return jsonify({"error": "Invalid position specified"})
    try:
        epsg = int(re.match(r'epsg:(\d+)', request.args['crs'], re.IGNORECASE).group(1))
    except:
        return jsonify({"error": "Invalid projection specified"})

    answer = {}
    success = False
    errormsg = ""
    suffix = ""
    i = 0
    for datasource in datasources:
        datasource.get_height(tenant, pos, epsg)
        if datasource.elevation:
            answer.update({"elevation"+suffix: datasource.elevation})
            i += 1
            suffix = "_"+str(i)
            success = True
        else: errormsg = errormsg + datasource.name + ': ' + datasource.error +"; "
    answer.update({"errors": errormsg})
    if success: return jsonify(answer)
    else: abort(Response(errormsg, 500))


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
    datasources = get_datasource(tenant)
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
    success = False
    errormsg = ""
    suffix = ""
    i = 0
    for datasource in datasources:
        datasource.get_profile(tenant, query, epsg, numSamples)
        if datasource.elevations:
            answer.update({"elevations"+suffix: datasource.elevations})
            i += 1
            suffix = "_"+str(i)
            success = True
        else: errormsg = errormsg + datasource.name + ': ' + datasource.error +"; "
    answer.update({"errors": errormsg})
    if success: return jsonify(answer)
    else: abort(Response(errormsg, 500))

""" readyness probe endpoint """
@app.route("/ready", methods=['GET'])
def ready():
    return jsonify({"status": "OK"})

""" liveness probe endpoint """
@app.route("/healthz", methods=['GET'])
def healthz():
    datasource = get_datasource(tenant_handler.tenant())
    if datasource is None:
        return make_response(jsonify({
            "status": "FAIL", "cause": "Failed to open elevation_dataset"}), 500)

    return jsonify({"status": "OK"})

if __name__ == "__main__":
    from flask_cors import CORS
    CORS(app)
    app.run(host='localhost', port=5002, debug=True)
