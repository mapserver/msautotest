# -*- coding: utf-8 -*-
###############################################################################
#
# Project:  MapServer
# Purpose:  XML validator
# Author:   Even Rouault, <even dot rouault at mines-paris dot org>
#
###############################################################################
# Copyright (C) 2013, Even Rouault
# Portions coming from EOxServer
# ( https://github.com/EOxServer/eoxserver/blob/master/eoxserver/services/testbase.py )
#   Copyright (C) 2011 EOX IT Services GmbH
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies of this Software or works derived from this Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
###############################################################################

import os
import sys
import urllib2
import socket
from lxml import etree

###############################################################################
# Remove mime header if found
def ingest_file_and_strip_mime(filename):
    data = ''
    f = open(filename, 'rb')
    for line in f.readlines():
        if line == '\r\n':
            continue
        if line == '\n':
            continue
        if line.find('Content-Type') >= 0:
            continue
        data = data + line
    f.close()
    return data

###############################################################################
# Replace http://schemas.opengis.net/foo by $(ogc_schemas_location)/foo

def substitute_ogc_schemas_location(location, ogc_schemas_location):
    if ogc_schemas_location is not None and \
        location.startswith('http://schemas.opengis.net/'):
        location = ogc_schemas_location + '/' + location[len('http://schemas.opengis.net/'):]
    return location

###############################################################################
# Validation function

def validate(xml_filename_or_content, xsd_filename = None, \
             application_schema_ns = 'http://mapserver.gis.umn.edu/mapserver', \
             ogc_schemas_location = None):

    try:
        if xml_filename_or_content.find('<?xml') == 0:
            doc = etree.XML(xml_filename_or_content)
        else:
            doc = etree.XML(ingest_file_and_strip_mime(xml_filename_or_content))
    except etree.Error as e:
        print(str(e))
        return False

    # Special case if this is a schema
    if doc.tag == '{http://www.w3.org/2001/XMLSchema}schema':
        for child in doc:
            if child.tag == '{http://www.w3.org/2001/XMLSchema}import':
                    location = child.get('schemaLocation')
                    location = substitute_ogc_schemas_location(location, ogc_schemas_location)
                    child.set('schemaLocation', location)
        try:
            etree.XMLSchema(etree.XML(etree.tostring(doc)))
            return True
        except etree.Error as e:
            print(str(e))
            return False

    schema_locations = doc.get("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation")
    if schema_locations is None:
        print('No schemaLocation found')
        return False

    # Our stripped GetFeature document have an empty timeStamp, put a
    # fake value one instead
    if doc.get('timeStamp') == '':
        doc.set('timeStamp', '1970-01-01T00:00:00Z')

    locations = schema_locations.split()

    # get schema locations
    schema_def = etree.Element("schema", attrib={
            "elementFormDefault": "qualified",
            "version": "1.0.0",
        }, nsmap={
            None: "http://www.w3.org/2001/XMLSchema"
        }
    )

    tempfiles = []

    # Special case for the main application schema
    for ns, location in zip(locations[::2], locations[1::2]):
        if ns == application_schema_ns:
            if xsd_filename is not None:
                location = xsd_filename
            else:
                location = os.path.splitext(xml_filename_or_content)[0] + '.xsd'

            # Remove mime-type header line if found to generate a valid .xsd
            sanitized_content = ingest_file_and_strip_mime(location)
            location = '/tmp/tmpschema%d.xsd' % len(tempfiles)
            f = open(location, 'wb')
            f.write(sanitized_content)
            tempfiles.append(location)
            f.close()

            xsd = etree.XML(sanitized_content)
            for child in xsd:
                if child.tag == '{http://www.w3.org/2001/XMLSchema}import':
                    sub_ns = child.get('namespace')
                    sub_location = child.get('schemaLocation')
                    sub_location = substitute_ogc_schemas_location(sub_location, ogc_schemas_location)
                    etree.SubElement(schema_def, "import", attrib={
                        "namespace": sub_ns,
                        "schemaLocation": sub_location
                        }
                    )

            etree.SubElement(schema_def, "import", attrib={
                    "namespace": ns,
                    "schemaLocation": location
                }
            )

    # Add each schemaLocation as an import
    for ns, location in zip(locations[::2], locations[1::2]):
        if ns == application_schema_ns:
            continue
        location = substitute_ogc_schemas_location(location, ogc_schemas_location)
        etree.SubElement(schema_def, "import", attrib={
                "namespace": ns,
                "schemaLocation": location
            }
        )

    # TODO: ugly workaround. But otherwise, the doc is not recognized as schema
    #print(etree.tostring(schema_def))
    schema = etree.XMLSchema(etree.XML(etree.tostring(schema_def)))

    try:
        schema.assertValid(doc)
        ret = True
    except etree.Error as e:
        print(str(e))
        ret = False

    for filename in tempfiles:
        os.remove(filename)

    return ret

###############################################################################
# Return a handle on a URL

def gdalurlopen(url):
    timeout = 60
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)

    if 'GDAL_HTTP_PROXY' in os.environ:
        proxy = os.environ['GDAL_HTTP_PROXY']

        if 'GDAL_HTTP_PROXYUSERPWD' in os.environ:
            proxyuserpwd = os.environ['GDAL_HTTP_PROXYUSERPWD']
            proxyHandler = urllib2.ProxyHandler({"http" : \
                "http://%s@%s" % (proxyuserpwd, proxy)})
        else:
            proxyuserpwd = None
            proxyHandler = urllib2.ProxyHandler({"http" : \
                "http://%s" % (proxy)})

        opener = urllib2.build_opener(proxyHandler, urllib2.HTTPHandler)

        urllib2.install_opener(opener)

    try:
        handle = urllib2.urlopen(url)
        socket.setdefaulttimeout(old_timeout)
        return handle
    except urllib2.HTTPError, e:
        print('HTTP service for %s is down (HTTP Error: %d)' % (url, e.code))
        socket.setdefaulttimeout(old_timeout)
        return None
    except urllib2.URLError, e:
        print('HTTP service for %s is down (HTTP Error: %s)' % (url, e.reason))
        socket.setdefaulttimeout(old_timeout)
        return None
    except:
        print('HTTP service for %s is down.' %(url))
        socket.setdefaulttimeout(old_timeout)
        return None

###############################################################################
# Download a file

def download(url, output_file):
    try:
        handle = gdalurlopen(url)
        try:
            handle_info = handle.info()
            content_length = handle_info['content-length']
            print('Downloading %s (length = %s bytes)...' % (url, content_length))
        except:
            print('Downloading %s...' % (url))
        ret = handle.read()
    except:
        ret = None
    if ret is None:
        print('Cannot download %s' % url)
        sys.exit(1)

    f = open(output_file, 'wb')
    f.write(ret)
    f.close()

###############################################################################
# Unzip a file

def unzip(zipfilename, target_dir):

    try:
        import zipfile
        zf = zipfile.ZipFile(zipfilename)
    except:
        os.system('unzip -d ' + target_dir + ' ' + zipfilename)
        return

    for filename in zf.namelist():
        print(filename)
        outfilename = os.path.join(target_dir, filename)
        if filename.endswith('/'):
            if not os.path.exists(outfilename):
               os.makedirs(outfilename)
        else:
            outdirname = os.path.dirname(outfilename)
            if not os.path.exists(outdirname):
               os.makedirs(outdirname)

            outfile = open(outfilename,'wb')
            outfile.write(zf.read(filename))
            outfile.close()

    return

###############################################################################
# Transform absolute schemaLocations into relative ones

def transform_abs_links_to_ref_links(path, level = 0):
    for file in os.listdir(path):
        filename=path + '/' + file
        if os.path.isdir(filename) and filename.find('examples') < 0:
            transform_abs_links_to_ref_links(filename, level+1)
        elif filename.endswith('.xsd'):
            #print(level)
            #print(filename)
            f = open(filename, 'rb')
            lines = f.readlines()
            f.close()
            rewrite = False
            for i in range(len(lines)):
                l = lines[i]
                if l[-1] == '\n':
                    l = l[0:-1]
                pos = l.find('http://schemas.opengis.net/')
                if pos >= 0:
                    rewrite = True
                    s = l[0:pos]
                    for j in range(level):
                        s = s + "../"
                    s = s + l[pos + len('http://schemas.opengis.net/'):]
                    l = s
                    lines[i] = l

                pos = l.find('http://www.w3.org/1999/xlink.xsd')
                if pos >= 0:
                    rewrite = True
                    s = l[0:pos]
                    for j in range(level):
                        s = s + "../"
                    s = s + l[pos + len('http://www.w3.org/1999/'):]
                    l = s
                    lines[i] = l

                pos = l.find('http://www.w3.org/2001/xml.xsd')
                if pos >= 0:
                    rewrite = True
                    s = l[0:pos]
                    for j in range(level):
                        s = s + "../"
                    s = s + l[pos + len('http://www.w3.org/2001/'):]
                    l = s
                    lines[i] = l

            if rewrite:
                f = open(filename, 'wb')
                f.writelines(lines)
                f.close()

###############################################################################
# Download OGC schemas

def download_ogc_schemas(ogc_schemas_url = 'http://schemas.opengis.net/SCHEMAS_OPENGIS_NET.zip', \
                         xlink_xsd_url = 'http://www.w3.org/1999/xlink.xsd', \
                         xml_xsd_url = 'http://www.w3.org/2001/xml.xsd', \
                         target_dir = '.', \
                         target_subdir = 'SCHEMAS_OPENGIS_NET'):
    try:
        os.stat(target_dir + '/' + 'SCHEMAS_OPENGIS_NET.zip')
    except:
        schemas = download(ogc_schemas_url, target_dir + '/' + 'SCHEMAS_OPENGIS_NET.zip')

    try:
        os.stat(target_dir + '/' + target_subdir + '/wfs')
    except:
        try:
            os.mkdir(target_dir + '/' + target_subdir)
        except:
            pass

        unzip(target_dir + '/' + 'SCHEMAS_OPENGIS_NET.zip', target_dir + '/' + target_subdir)
        try:
            os.stat(target_dir + '/' + target_subdir + '/wfs')
        except:
            print('Cannot unzip SCHEMAS_OPENGIS_NET.zip')
            sys.exit(1)

    try:
        os.stat(target_dir + '/' + target_subdir + '/xlink.xsd')
    except:
        schemas = download(xlink_xsd_url, target_dir + '/' + target_subdir + '/xlink.xsd')

    try:
        os.stat(target_dir + '/' + target_subdir + '/xml.xsd')
    except:
        schemas = download(xml_xsd_url, target_dir + '/' + target_subdir + '/xml.xsd')

    transform_abs_links_to_ref_links(target_dir + '/' + target_subdir)

###############################################################################
# has_local_ogc_schemas()

def has_local_ogc_schemas(path):

    # Autodetect OGC schemas
    try:
        os.stat(path + '/wfs')
        os.stat(path + '/xlink.xsd')
        os.stat(path + '/xml.xsd')

        if False:
            try:
                os.stat(path + '/ogc_catalog.xml')
            except:
                f = open(path + '/ogc_catalog.xml', 'wb')
                f.write("""<?xml version="1.0"?>
    <!DOCTYPE catalog PUBLIC "-//OASIS//DTD Entity Resolution XML Catalog V1.0//EN" "http://www.oasis-open.org/committees/entity/release/1.0/catalog.dtd">
    <catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
    <rewriteSystem systemIdStartString="http://schemas.opengis.net/" rewritePrefix="./"/>
    <rewriteURI uriStartString="http://schemas.opengis.net/" rewritePrefix="./"/>

    <rewriteURI uriStartString="http://www.w3.org/1999/xlink.xsd" rewritePrefix="./xlink.xsd"/>

    <rewriteURI uriStartString="http://www.w3.org/2001/xml.xsd" rewritePrefix="./xml.xsd"/>
    </catalog>
    """)
                f.close()
            os.environ['XML_CATALOG_FILES'] = path + '/ogc_catalog.xml'
        return True
    except:
        return False

###############################################################################
# Usage function

def Usage():
    print('Usage: validate.py [-download_ogc_schemas] [-schema some.xsd] [-ogc_schemas_location path] some.xml')
    sys.exit(255)

###############################################################################
# Main

if __name__ == '__main__':
    argv = sys.argv[1:]
    i = 0
    filename = None
    xsd_filename = None
    ogc_schemas_location = None
    
    if has_local_ogc_schemas('SCHEMAS_OPENGIS_NET'):
        ogc_schemas_location = 'SCHEMAS_OPENGIS_NET'

    while i < len(argv):
        if argv[i] == "-download_ogc_schemas":
            download_ogc_schemas()
            if i == len(argv)-1:
                sys.exit(0)
        elif argv[i] == "-schema":
            i = i + 1
            xsd_filename = argv[i]
        elif argv[i] == "-ogc_schemas_location":
            i = i + 1
            ogc_schemas_location = argv[i]
        elif argv[i][0] == '-':
            print('Unhandled option : %s' % argv[i])
            print('')
            Usage()
        else:
            filename = argv[i]

        i = i + 1

    if filename is None:
        Usage()

    if validate(filename, xsd_filename = xsd_filename, ogc_schemas_location = ogc_schemas_location):
        sys.exit(0)
    else:
        sys.exit(1)
