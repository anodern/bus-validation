import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.parse
import urllib.request

from route import Route, RouteMaster


def validation(city, osm):
    print('this is a validation')
    route_master_list = {}
    route_list = []
    
    for item in osm:
        if item['type'] == 'area':
            logging.info('City:{}'.format(item['tags']['name']))
        elif item['type'] == 'relation':
            if item['id'] == city:
                print('cnm')
                continue
            if item['tags']['type'] == 'route':
                route_list.append(Route(item['id'], item['tags'], None))
          
    for route in route_list:
        # print(route)
        if route.ref not in route_master_list:
            route_master_list[route.ref] = RouteMaster(route.ref, None, city)
        route_master_list[route.ref].routes.append(route)

    for ref in route_master_list:
        print(route_master_list[ref])
        