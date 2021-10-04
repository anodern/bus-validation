import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.parse
import urllib.request

from validation import validation


def overpass_request(overpass_api, city_relation_id):
    city_relation_id = 12601507
    query = '[out:json][timeout:1000];(relation({});map_to_area;'.format(city_relation_id)
    query += 'rel[type=route][route=bus](area););out tags qt;'
    logging.debug('Query: %s', query)

    logging.debug('Query: %s', query)
    url = '{}?data={}'.format(overpass_api, urllib.parse.quote(query))
    response = urllib.request.urlopen(url, timeout=1000)
    if response.getcode() != 200:
        raise Exception('Failed to query Overpass API: HTTP {}'.format(response.getcode()))
    return json.load(response)['elements']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--source', help='File to write backup of OSM data, or to read data from')
    parser.add_argument('-x', '--xml', help='OSM extract with routes, to read data from')
    parser.add_argument('--overpass-api', default='http://overpass-api.de/api/interpreter', help="Overpass API URL")
    parser.add_argument('-q', '--quiet', action='store_true', help='Show only warnings and errors')
    parser.add_argument('-c', '--city', help='Validate only a single city or a country')
    # parser.add_argument('-t','--overground',action='store_true',help='Process overground transport instead of subway')
    # parser.add_argument('-e','--entrances',type=argparse.FileType('w', encoding='utf-8'),
    # help='Export unused subway entrances as GeoJSON here')
    parser.add_argument('-l', '--log', type=argparse.FileType('w', encoding='utf-8'), help='Validation JSON file name')
    parser.add_argument('-o','--output',type=argparse.FileType('w',encoding='utf-8'),help='Processed bus systems output')
    parser.add_argument('--cache', help='Cache file name for processed data')
    parser.add_argument('-r', '--recovery-path', help='Cache file name for error recovery')
    parser.add_argument('-d', '--dump', help='Make a YAML file for a city data')
    parser.add_argument('-j', '--geojson', help='Make a GeoJSON file for a city data')
    parser.add_argument('--crude', action='store_true', help='Do not use OSM railway geometry for GeoJSON')
    options = parser.parse_args()
    
    options.city = '12601507'  # 范围relation id

    if options.quiet:
        log_level = logging.WARNING
    else:
        log_level = logging.INFO
    logging.basicConfig(level=log_level, datefmt='%H:%M:%S', format='%(asctime)s %(levelname)-7s  %(message)s')
    
    # Reading cached json, loading XML or querying Overpass API
    if options.source and os.path.exists(options.source):
        logging.info('Reading data from %s', options.source)
        with open(options.source, 'r', encoding='utf-8') as f:
            osm = json.load(f)
            if 'elements' in osm:
                osm = osm['elements']
    else:
        logging.info('Downloading data from Overpass API')
        osm = overpass_request(options.overpass_api, options.city)
        if options.source:
            with open(options.source, 'w', encoding='utf-8') as f:
                json.dump(osm, f)
    logging.info('Downloaded %s elements', len(osm))
    
    validation(options.city, osm)

    

