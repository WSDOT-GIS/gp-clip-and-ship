# ###########################################################################################
# Name: ClipandShip.py
# Description: Use a geometry to download and clip part of the image service. Then organize
#              the data inside the mosaic dataset
#
# Requierments: Must Supply a image service url and a polygon geometry
#
# Created: March, 2012
# ###########################################################################################

import arcpy, sys, os, traceback
from arcpy import env
from arcpy import da
import urllib2
import json
import datetime


# Get general image service info: Spatial reference, Pixel Type, etc
def getISinfo(serviceURL):
    
    try:
        # Sending request for general service info
        post_data = ""
        
        headers = {}
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        
        serviceURL = serviceURL.replace("arcgis/services", "arcgis/rest/services")+"?f=json"                
        
        # Send general server request
        req = urllib2.Request(serviceURL, post_data, headers)
        response_stream = urllib2.urlopen(req)
        response = response_stream.read()    
        
        jsondict = json.loads(response)    
        isprj = jsondict["extent"]["spatialReference"]
        pixtype = jsondict["pixelType"]
        defaultrr = jsondict["rasterFunctionInfos"][0]["name"]
        
        return isprj, pixtype, defaultrr
    except:
        arcpy.AddError("ERROR: Failure in getting the general service info")

# Generate spatial selection and query for fields through REST
def getQueryFields(serviceURL, polygonfeat): 

    try:
        arcpy.AddMessage("Getting raster IDs and attributes by location...")
        # Convert polygon feature class to JSON geometry
        # Step 1: convert polygon to points
        arcpy.env.overwriteOutput = 1
        verticespnt = "in_memory/verpnt"
        arcpy.FeatureVerticesToPoints_management(polygonfeat, verticespnt)
        # Step 2: add coordinates of point to the feature class
        arcpy.AddXY_management(verticespnt)
        # Step 3: Read the point coordinate from feature class to an array
        verticesxy = []
        fieldNames = ["POINT_X", "POINT_Y"]
        with arcpy.da.SearchCursor(verticespnt, fieldNames) as rows:
            for row in rows:
                verticesxy.append([row[0], row[1]])
        
        # Get the spatial reference code of the polygon feature
        desc = arcpy.Describe(polygonfeat)
        factcode = desc.SpatialReference.FactoryCode
        
        # Constructing Query REST request
        geometry = "&geometry={ 'rings': ["+str(verticesxy)+"],'spatialReference':{'wkid':"+str(factcode)+"}}&geometryType=esriGeometryPolygon"
        content = "where=CATEGORY=1"+geometry+"&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=false&f=json"
        
        post_data = unicode(content, "utf-8")
        
        headers = {}
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        
        serviceURL = serviceURL.replace("arcgis/services", "arcgis/rest/services")+"/query"
        
        # Send Query request to get item attributes
        req = urllib2.Request(serviceURL, post_data, headers)
        response_stream = urllib2.urlopen(req)
        response = response_stream.read()    
        
        jsondict = json.loads(response)    
        itemfields = jsondict["fields"]
        itemfeatures = jsondict["features"]
        
        return itemfields, itemfeatures
    except:
        arcpy.AddError("Failure in getQueryFields function")

# Get bounding box for each geometry
def getbbox(polygonfeat, itemgeo, isprj):
    
    try:
        
        '''
        Find the intersection between footprint polygon and clipping feature
        '''
        #Create point list to hold the point object
        point = arcpy.Point()
        array = arcpy.Array()
        itempoly = []
        
        #Construct polygon feature from points
        for coordPair in itemgeo:
            point.X = coordPair[0]
            point.Y = coordPair[1]
            array.add(point)
        
        itempoly.append(arcpy.Polygon(array))        
        arcpy.env.overwriteOutput = 1
        fpfeat = "in_memory/fpfeat"
        #fpfeat = r"e:\temp\clipandship\fpfeat.shp"
        arcpy.CopyFeatures_management(itempoly, fpfeat)
        arcpy.DefineProjection_management(fpfeat, isprj)
        
        #Find intersection between clipping polygon and footprint
        #Note: if two features class are in different projection, output should be 
        #      in image service projection
        interfeat = "in_memory/interfeat"
        #interfeat = r"e:\temp\clipandship\interfeat.shp"
        arcpy.Intersect_analysis(fpfeat+";"+polygonfeat, interfeat)
        
        #Convert the intersecting polygon to vertice points
        verticespnt = "in_memory/verpnt"
        arcpy.FeatureVerticesToPoints_management(interfeat, verticespnt)
        
        #Get intersection polygon vertices to a list
        arcpy.AddXY_management(verticespnt)
        verticesxy = []
        fieldNames = ["POINT_X", "POINT_Y"]
        with arcpy.da.SearchCursor(verticespnt, fieldNames) as rows:
            for row in rows:
                verticesxy.append([row[0], row[1]])        
        
        desc = arcpy.Describe(interfeat)
        bbox = []
        bbox.append(desc.extent.XMin)
        bbox.append(desc.extent.YMin)
        bbox.append(desc.extent.XMax)
        bbox.append(desc.extent.YMax)
        
        return bbox
      
    except:
        arcpy.AddError("ERROR: Failure in get bounding box")


#Download raster by exporting the mosaic dataset item to GeoTIFF images
def downloaditem(serviceURL, itemoid, defaultrr, bbox, cellsize, isprj, pixtype, userr, outputws):
    
    try:
        '''
        Construct "Export Image" query content
        '''
        #Define bounding box string
        ibbox = "&bbox="+str(bbox).lstrip("[").rstrip("]")
        
        #Get image size according to the cell size
        width = abs(int((bbox[2]-bbox[0])/cellsize))
        height = abs(int((bbox[3]-bbox[1])/cellsize))
        isize = "&size="+str(width)+","+str(height)
        
        #Define output image spatial reference
        imageSR = "&imageSR="+str(isprj).replace("u'","'")
        
        #Define bounding box spatial reference
        bboxSR = "&bboxSR="+str(isprj).replace("u'","'")
        
        #Define output format and pixel type
        oformat = "&format=tiff&pixelType="+pixtype
        
        #Define mosiac rule 
        mosaicRule = "&mosaicRule={'mosaicMethod' : 'esriMosaicLockRaster', 'lockRasterIds' : ["+str(itemoid)+"]}"
        
        #Define rendering rule for download
        if userr:
            rrule = {"rasterFunction": str(defaultrr)}
        else:
            rrule = {"rasterFunction": "None"}
        renderingRule = "&renderingRule="+str(rrule)
        
        #Constructing Export Image REST request
        content = "f=json" + ibbox + isize + imageSR + bboxSR + oformat + mosaicRule + renderingRule
        
        post_data = content
        
        headers = {}
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        
        serviceURL = serviceURL.replace("arcgis/services", "arcgis/rest/services")+"/exportImage"
        
        #Read response from server and find image url 
        arcpy.AddMessage("Requesting to download image id = " + str(itemoid))
        req = urllib2.Request(serviceURL, post_data, headers)
        response_stream = urllib2.urlopen(req)
        response = response_stream.read()    
        
        jsondict = json.loads(response)    
        imageurl = jsondict["href"]        
        
        #Retrive image url from server
        file_name = os.path.join(outputws, "mdimage"+str(itemoid)+".tif")
        if arcpy.Exists(file_name):
            arcpy.Delete_management(file_name)
        localFile = open(file_name, 'wb')      
        localFile.write(urllib2.urlopen(imageurl).read())
        
        localFile.close()
        arcpy.AddMessage("Successfully download image id = " + str(itemoid)) 
        
        return file_name
    except:
        arcpy.AddError("ERROR: Failure in the download item process")
        return ""

#Clip the output image if necessary
def clipimage(file_name, polygonfeat, itemoid, nodataVal):

    try:
        arcpy.AddMessage("Clipping image id = " + str(itemoid))
        
        #Clip the image to the polygon geometry        
        arcpy.env.overwriteOutput = 1
        out_name = file_name[:-4]+"_clip"+file_name[-4:]
        clipgeo = "ClippingGeometry"
        
        #Clip download image
        arcpy.Clip_management(file_name, "", out_name, polygonfeat, nodataVal, clipgeo)
        
        #Delete original download image
        arcpy.Delete_management(file_name)
        
        arcpy.AddMessage("Successfully clipped image id = " + str(itemoid))    
    except:
        arcpy.AddError("ERROR: Failure in clipping the output image")

def getfieldTypeKey(fieldtype):
    
    if fieldtype == "esriFieldTypeDouble":
        return "DOUBLE"
    elif fieldtype == "esriFieldTypeString":
        return "TEXT"
    elif fieldtype == "esriFieldTypeInteger":
        return "LONG"
    elif fieldtype == "esriFieldTypeSmallInteger":
        return "SHORT"
    elif fieldtype == "esriFieldTypeDate":
        return "DATE"
    elif fieldtype == "esriFieldTypeBlob":
        return "BLOB"
    elif fieldtype == "esriFieldTypeGUID":
        return "GUID"
    elif fieldtype == "esriFieldTypeSingle":
        return "FLOAT"
    else:
        return "LONG"

# Recover the fields from the image service to the output mosaic dataset
def recoverFields(itemfields, mdpath):
    
    try:
        # Get field names from image service
        isfieldsName = [field["name"].lower() for field in itemfields]    
        
        # Get field names from mosaic dataset
        mdfields = arcpy.ListFields(mdpath)
        mdfieldsName = [field.name.lower() for field in mdfields]
        mdfieldsName.remove("raster")
        
        missingfieldsName = [x for x in isfieldsName if x not in mdfieldsName]
        
        if len(missingfieldsName) > 0:            
            for fieldname in missingfieldsName:                
                
                arcpy.AddMessage("Adding missing field %s to the output mosaic dataset..." % fieldname)
                
                mfield = filter(lambda mfield: mfield["name"].lower() == fieldname, itemfields)[0]
                ftype = getfieldTypeKey(mfield["type"])
                fprecision = ""
                fscale = ""
                flength = mfield["length"] if mfield.has_key("length") else ""
                falias = mfield["alias"] if mfield.has_key("alias") else ""
                fnullable = ""
                frequire = ""
                fdomain = mfield["domain"] if mfield.has_key("domain") else ""
                
                # Add missing field to the mosaic dataset
                arcpy.AddField_management(mdpath, fieldname, ftype, fprecision, fscale, flength,
                                          falias, fnullable, frequire)
                
                # Add domain if exist
                if fdomain != "" and fdomain != None:
                    domainDict = fdomain["codedValues"]
                    for code in domainDict:
                        arcpy.AddCodedValueToDomain_management(os.path.dirname(mdpath), fdomain["name"],
                                                               code["code"], code["name"])
                    arcpy.AssignDomainToField_management(mdpath, fieldname, fdomain["name"])
        
        # Optional: add an extra OID field to save ids in the original image service
        arcpy.AddField_management(mdpath, "OOID", "LONG")
    except:
        arcpy.AddError("ERROR: Failure in the recoverFields function")

# Add output raster datasets to the mosaic dataset and recover field values
def addrasters(mdpath, outputws, itematt):
    
    try:
        arcpy.AddMessage("Adding the download raster to mosaic dataset...")
        rastype = "Raster Dataset"        
        
        # Add downloaded raster to mosaic dataset, exclude duplicated item
        arcpy.AddRastersToMosaicDataset_management(mdpath, rastype, outputws, "","","","","",
                                                   "","","","","EXCLUDE_DUPLICATES")
        
        # recover field values
        arcpy.AddMessage("Copying field values from Image Service to Mosaic Dataset...")
        # no need to recover name and shape
        del itematt["Name"]
        del itematt["Shape_Length"]
        del itematt["Shape_Area"]        
        
        # find the last row in the mosaic dataset to update
        whereclause = """OBJECTID=%s""" % arcpy.GetCount_management(mdpath).getOutput(0)
        
        # get date field names
        mdfields = arcpy.ListFields(mdpath)
        datefieldsName = []
        for mdfield in mdfields:
            if mdfield.type == "Date":
                datefieldsName.append(mdfield.name.lower())
        
        cursor = arcpy.da.UpdateCursor(mdpath, "*", whereclause)
        # create mosaic dataset field name list to search the index
        mdfieldNamesUpper = cursor.fields
        mdfieldNames = [x.lower() for x in mdfieldNamesUpper]
        
        lastrow = cursor.next()
        for fieldName in itematt:
            fieldVal = itematt[fieldName]
            # Save the OBJECTID to the OOID field
            if fieldName.lower() == "objectid":
                findex = mdfieldNames.index("ooid")
                lastrow[findex] = fieldVal
            else: 
                findex = mdfieldNames.index(fieldName.lower())
                # Recover date field
                if fieldName.lower() in datefieldsName:                    
                    dateval = datetime.datetime.utcfromtimestamp(fieldVal/1000)
                    lastrow[findex] = dateval
                else:
                    lastrow[findex] = fieldVal
        cursor.updateRow(lastrow)
        
    except:
        arcpy.AddError("ERROR: Failure in adding output to mosaic dataset")

def main(*argv):
    """
        Main function for data discovery
    """
    try:
        # Read user input
        #
        servicelayer = argv[0]
        outputws = argv[1]
        outputgdb = argv[2]
        mdname = argv[3]
        polygonfeat = argv[4]
        cellsize = float(argv[5])
        clipping = argv[6]
        nodataVal = float(argv[7])
        userr = argv[8]
        
        #... read more as optional parameters
        
        # Check image service layer or URL
        if not arcpy.Exists(servicelayer):
            if servicelayer.startswith("http") and servicelayer.lower().find("imageserver") != -1:
                arcpy.AddMessage("Input is a service URL")
                serviceURL = servicelayer
            else:
                arcpy.AddError("Invalid Input.")
                return
        else:
            islayer = arcpy.mapping.Layer(servicelayer)           
            # Check if the image service is from mosaic dataset
            if not (islayer.isServiceLayer and islayer.isRasterLayer):
                arcpy.AddError("Layer is not Image Service layer")
                return 
            elif not islayer.supports("DEFINITIONQUERY"):
                arcpy.AddError("Image Service is not publish from Mosaic Dataset")
                return
            # Get service URL from the image service layer
            serviceURL = islayer.serviceProperties["URL"]            
        
        # Get general service information
        inforeq = getISinfo(serviceURL)
        isprj = inforeq[0]
        pixtype = inforeq[1]
        defaultrr = inforeq[2]
        
        # Get spatial query request, item fields, values and spatial reference
        queryres = getQueryFields(serviceURL, polygonfeat)        
        itemfields = queryres[0]
        itemfeatures = queryres[1]
        
        # Define output mosaic dataset path
        mdpath = os.path.join(outputgdb, mdname)
        
        # Check if there is items to download
        if len(itemfeatures) > 0:
            
            arcpy.AddMessage("Found items to download, creating mosaic dataset...")
            mdprj = arcpy.CreateSpatialReference_management(isprj["wkid"])
            
            # Create output mosaic dataset and recover fields
            # Create File GDB for shipping md
            if not arcpy.Exists(outputgdb):
                arcpy.CreateFileGDB_management(os.path.dirname(outputgdb), os.path.basename(outputgdb))
            # Create output mosaic dataset
            arcpy.env.overwriteOutput = 1
            arcpy.CreateMosaicDataset_management(outputgdb, mdname, mdprj)
            
            # Recover fields from the image service
            missingfieldsName = recoverFields(itemfields, mdpath)            
        else:
            arcpy.AddError("No raster can be downloaded")
        
        # Download raster one by one, and add raster one by one
        for itemfeature in itemfeatures:
            itematt = itemfeature["attributes"]
            itemgeo = itemfeature["geometry"]["rings"][0]
            itemoid = itematt["OBJECTID"]
            
            #Get clipping bounding box for each item
            bbox = getbbox(polygonfeat, itemgeo, mdprj)
            #Generate download image
            file_name = downloaditem(serviceURL, itemoid, defaultrr, bbox, cellsize, isprj, pixtype, userr, outputws)
            #Clip output image to polygon geometry if clipping is true
            if clipping:
                clipimage(file_name, polygonfeat, itemoid, nodataVal)
            
            # Add downloaded raster to output mosaic dataset
            addrasters(mdpath, outputws, itematt)
        
        arcpy.AddMessage("All done")
        
    except:
        arcpy.AddError("Clip and ship application failed")


if __name__ == "__main__":
    argv = tuple(arcpy.GetParameterAsText(i)
                 for i in range(arcpy.GetArgumentCount()))
    main(*argv)