import csv
import logging
import math
import urllib.parse
import urllib.request
from css_colours import normalize_colour
from collections import Counter, defaultdict

SPREADSHEET_ID = '1SEW1-NiNOnA2qDwievcxYV1FOaQl1mb1fdeyqAxHu3k'
MAX_DISTANCE_TO_ENTRANCES = 300  # in meters
MAX_DISTANCE_STOP_TO_LINE = 50  # in meters
ALLOWED_STATIONS_MISMATCH = 0.02  # part of total station count
ALLOWED_TRANSFERS_MISMATCH = 0.07  # part of total interchanges count
ALLOWED_ANGLE_BETWEEN_STOPS = 45  # in degrees
DISALLOWED_ANGLE_BETWEEN_STOPS = 20  # in degrees

# If an object was moved not too far compared to previous script run,
# it is likely the same object
DISPLACEMENT_TOLERANCE = 300  # in meters

MODES_RAPID = {'subway', 'light_rail', 'monorail', 'train'}
MODES_OVERGROUND = {'tram', 'bus', 'trolleybus', 'aerialway', 'ferry'}
DEFAULT_MODES_RAPID = {'subway', 'light_rail'}
DEFAULT_MODES_OVERGROUND = {'tram'}  # TODO: bus and trolleybus?
ALL_MODES = MODES_RAPID | MODES_OVERGROUND
RAILWAY_TYPES = {'rail', 'light_rail', 'subway', 'narrow_gauge', 'funicular', 'monorail', 'tram'}
CONSTRUCTION_KEYS = (
    'construction',
    'proposed',
    'construction:railway',
    'proposed:railway',
)

class City:
    def __init__(self, row, overground=False):
        self.errors = []
        self.warnings = []
        self.name = row[1]
        self.country = row[2]
        self.continent = row[3]
        if not row[0]:
            self.error('City {} does not have an id'.format(self.name))
        self.id = int(row[0] or '0')
        self.overground = overground
        if not overground:
            self.num_stations = int(row[4])
            self.num_lines = int(row[5] or '0')
            self.num_light_lines = int(row[6] or '0')
            self.num_interchanges = int(row[7] or '0')
        else:
            self.num_tram_lines = int(row[4] or '0')
            self.num_trolleybus_lines = int(row[5] or '0')
            self.num_bus_lines = int(row[6] or '0')
            self.num_other_lines = int(row[7] or '0')
        
        # Aquiring list of networks and modes
        networks = None if len(row) <= 9 else row[9].split(':')
        if not networks or len(networks[-1]) == 0:
            self.networks = []
        else:
            self.networks = set(
                filter(None, [x.strip() for x in networks[-1].split(';')])
            )
        if not networks or len(networks) < 2 or len(networks[0]) == 0:
            if self.overground:
                self.modes = DEFAULT_MODES_OVERGROUND
            else:
                self.modes = DEFAULT_MODES_RAPID
        else:
            self.modes = set([x.strip() for x in networks[0].split(',')])
        
        # Reversing bbox so it is (xmin, ymin, xmax, ymax)
        bbox = row[8].split(',')
        if len(bbox) == 4:
            self.bbox = [float(bbox[i]) for i in (1, 0, 3, 2)]
        else:
            self.bbox = None
        
        self.elements = {}  # Dict el_id → el
        self.stations = defaultdict(list)  # Dict el_id → list of StopAreas
        self.routes = {}  # Dict route_ref → route
        self.masters = {}  # Dict el_id of route → route_master
        self.stop_areas = defaultdict(list)  # El_id → list of el_id of stop_area
        self.transfers = []  # List of lists of stop areas
        self.station_ids = set()  # Set of stations' uid
        self.stops_and_platforms = set()  # Set of stops and platforms el_id
        self.recovery_data = None
    
    def log_message(self, message, el):
        if el:
            tags = el.get('tags', {})
            message += ' ({} {}, "{}")'.format(
                el['type'],
                el.get('id', el.get('ref')),
                tags.get('name', tags.get('ref', '')),
            )
        return message
    
    def warn(self, message, el=None):
        msg = self.log_message(message, el)
        self.warnings.append(msg)
    
    def error(self, message, el=None):
        msg = self.log_message(message, el)
        self.errors.append(msg)
    
    def error_if(self, is_error, message, el=None):
        if is_error:
            self.error(message, el)
        else:
            self.warn(message, el)
        
    def add(self, el):
        if el['type'] == 'relation' and 'members' not in el:
            return
        self.elements[el_id(el)] = el
        if el['type'] == 'relation' and 'tags' in el:
            if el['tags'].get('type') == 'route_master':
                for m in el['members']:
                    if m['type'] == 'relation':
                        if el_id(m) in self.masters:
                            self.error('Route in two route_masters', m)
                        self.masters[el_id(m)] = el
            elif el['tags'].get('public_transport') == 'stop_area':
                warned_about_duplicates = False
                for m in el['members']:
                    stop_areas = self.stop_areas[el_id(m)]
                    if el in stop_areas:
                        if not warned_about_duplicates:
                            self.warn('Duplicate element in a stop area', el)
                            warned_about_duplicates = True
                    else:
                        stop_areas.append(el)
    
    def make_transfer(self, sag):
        transfer = set()
        for m in sag['members']:
            k = el_id(m)
            el = self.elements.get(k)
            if not el:
                # A sag member may validly not belong to the city while
                # the sag does - near the city bbox boundary
                continue
            if 'tags' not in el:
                self.error('An untagged object {} in a stop_area_group'.format(k), sag)
                continue
            if (
                    el['type'] != 'relation'
                    or el['tags'].get('type') != 'public_transport'
                    or el['tags'].get('public_transport') != 'stop_area'
            ):
                continue
            if k in self.stations:
                stoparea = self.stations[k][0]
                transfer.add(stoparea)
                if stoparea.transfer:
                    self.error('Stop area {} belongs to multiple interchanges'.format(k))
                stoparea.transfer = el_id(sag)
        if len(transfer) > 1:
            self.transfers.append(transfer)
    
    def extract_routes(self):
        # Extract stations
        processed_stop_areas = set()
        for el in self.elements.values():
            if Station.is_station(el, self.modes):
                # See PR https://github.com/mapsme/subways/pull/98
                if el['type'] == 'relation' and el['tags'].get('type') != 'multipolygon':
                    self.error("A railway station cannot be a relation of type '{}'".format(el['tags'].get('type')),el,)
                    continue
                st = Station(el, self)
                self.station_ids.add(st.id)
                if st.id in self.stop_areas:
                    stations = []
                    for sa in self.stop_areas[st.id]:
                        stations.append(StopArea(st, self, sa))
                else:
                    stations = [StopArea(st, self)]
                
                for station in stations:
                    if station.id not in processed_stop_areas:
                        processed_stop_areas.add(station.id)
                        for st_el in station.get_elements():
                            self.stations[st_el].append(station)
                        
                        # Check that stops and platforms belong to single stop_area
                        for sp in station.stops | station.platforms:
                            if sp in self.stops_and_platforms:
                                self.warn(
                                    'A stop or a platform {} belongs to multiple '
                                    'stations, might be correct'.format(sp)
                                )
                            else:
                                self.stops_and_platforms.add(sp)
        
        # Extract routes
        for el in self.elements.values():
            if Route.is_route(el, self.modes):
                if el['tags'].get('access') in ('no', 'private'):
                    continue
                route_id = el_id(el)
                master = self.masters.get(route_id, None)
                if self.networks:
                    network = Route.get_network(el)
                    if master:
                        master_network = Route.get_network(master)
                    else:
                        master_network = None
                    if network not in self.networks and master_network not in self.networks:
                        continue
                
                route = Route(el, self, master)
                k = el_id(master) if master else route.ref
                if k not in self.routes:
                    self.routes[k] = RouteMaster(master)
                self.routes[k].add(route, self)
                
                # Sometimes adding a route to a newly initialized RouteMaster can fail
                if len(self.routes[k]) == 0:
                    del self.routes[k]
            
            # And while we're iterating over relations, find interchanges
            if (
                    el['type'] == 'relation'
                    and el.get('tags', {}).get('public_transport', None)
                    == 'stop_area_group'
            ):
                self.make_transfer(el)
        
        # Filter transfers, leaving only stations that belong to routes
        used_stop_areas = set()
        for rmaster in self.routes.values():
            for route in rmaster:
                used_stop_areas.update([s.stoparea for s in route.stops])
        new_transfers = []
        for transfer in self.transfers:
            new_tr = [s for s in transfer if s in used_stop_areas]
            if len(new_tr) > 1:
                new_transfers.append(new_tr)
        self.transfers = new_transfers
    
    def __iter__(self):
        return iter(self.routes.values())
    
    def is_good(self):
        return len(self.errors) == 0
    
    def get_validation_result(self):
        result = {
            'name': self.name,
            'country': self.country,
            'continent': self.continent,
            'stations_found': getattr(self, 'found_stations', 0),
            'transfers_found': getattr(self, 'found_interchanges', 0),
            'unused_entrances': getattr(self, 'unused_entrances', 0),
            'networks': getattr(self, 'found_networks', 0),
        }
        if not self.overground:
            result.update(
                {
                    'subwayl_expected': self.num_lines,
                    'lightrl_expected': self.num_light_lines,
                    'subwayl_found': getattr(self, 'found_lines', 0),
                    'lightrl_found': getattr(self, 'found_light_lines', 0),
                    'stations_expected': self.num_stations,
                    'transfers_expected': self.num_interchanges,
                }
            )
        else:
            result.update(
                {
                    'stations_expected': 0,
                    'transfers_expected': 0,
                    'busl_expected': self.num_bus_lines,
                    'trolleybusl_expected': self.num_trolleybus_lines,
                    'traml_expected': self.num_tram_lines,
                    'otherl_expected': self.num_other_lines,
                    'busl_found': getattr(self, 'found_bus_lines', 0),
                    'trolleybusl_found': getattr(
                        self, 'found_trolleybus_lines', 0
                    ),
                    'traml_found': getattr(self, 'found_tram_lines', 0),
                    'otherl_found': getattr(self, 'found_other_lines', 0),
                }
            )
        result['warnings'] = self.warnings
        result['errors'] = self.errors
        return result
    
    def count_unused_entrances(self):
        global used_entrances
        stop_areas = set()
        for el in self.elements.values():
            if (
                    el['type'] == 'relation'
                    and 'tags' in el
                    and el['tags'].get('public_transport') == 'stop_area'
                    and 'members' in el
            ):
                stop_areas.update([el_id(m) for m in el['members']])
        unused = []
        not_in_sa = []
        for el in self.elements.values():
            if (
                    el['type'] == 'node'
                    and 'tags' in el
                    and el['tags'].get('railway') == 'subway_entrance'
            ):
                i = el_id(el)
                if i in self.stations:
                    used_entrances.add(i)
                if i not in stop_areas:
                    not_in_sa.append(i)
                    if i not in self.stations:
                        unused.append(i)
        self.unused_entrances = len(unused)
        self.entrances_not_in_stop_areas = len(not_in_sa)
        if unused:
            self.warn('Found {} entrances not used in routes or stop_areas: {}'.format(
                len(unused), format_elid_list(unused)
            )
            )
        if not_in_sa:
            self.warn('{} subway entrances are not in stop_area relations: {}'.format(
                len(not_in_sa), format_elid_list(not_in_sa)
            )
            )
    
    def check_return_routes(self, rmaster):
        variants = {}
        have_return = set()
        for variant in rmaster:
            if len(variant) < 2:
                continue
            # Using transfer ids because a train can arrive at different stations within a transfer
            # But disregard transfer that may give an impression of a circular route
            # (for example, Simonis / Elisabeth station and route 2 in Brussels)
            if variant[0].stoparea.transfer == variant[-1].stoparea.transfer:
                t = (variant[0].stoparea.id, variant[-1].stoparea.id)
            else:
                t = (
                    variant[0].stoparea.transfer or variant[0].stoparea.id,
                    variant[-1].stoparea.transfer or variant[-1].stoparea.id,
                )
            if t in variants:
                continue
            variants[t] = variant.element
            tr = (t[1], t[0])
            if tr in variants:
                have_return.add(t)
                have_return.add(tr)
        
        if len(variants) == 0:
            self.error(
                'An empty route master {}. Please set construction:route '
                'if it is under construction'.format(rmaster.id)
            )
        elif len(variants) == 1:
            self.error_if(
                not rmaster.best.is_circular,
                'Only one route in route_master. '
                'Please check if it needs a return route',
                rmaster.best.element,
            )
        else:
            for t, rel in variants.items():
                if t not in have_return:
                    self.warn('Route does not have a return direction', rel)
    
    def validate_lines(self):
        self.found_light_lines = len(
            [x for x in self.routes.values() if x.mode != 'subway']
        )
        self.found_lines = len(self.routes) - self.found_light_lines
        if self.found_lines != self.num_lines:
            self.error(
                'Found {} subway lines, expected {}'.format(
                    self.found_lines, self.num_lines
                )
            )
        if self.found_light_lines != self.num_light_lines:
            self.error(
                'Found {} light rail lines, expected {}'.format(
                    self.found_light_lines, self.num_light_lines
                )
            )
    
    def validate_overground_lines(self):
        self.found_tram_lines = len(
            [x for x in self.routes.values() if x.mode == 'tram']
        )
        self.found_bus_lines = len(
            [x for x in self.routes.values() if x.mode == 'bus']
        )
        self.found_trolleybus_lines = len(
            [x for x in self.routes.values() if x.mode == 'trolleybus']
        )
        self.found_other_lines = len(
            [
                x
                for x in self.routes.values()
                if x.mode not in ('bus', 'trolleybus', 'tram')
            ]
        )
        if self.found_tram_lines != self.num_tram_lines:
            self.error_if(
                self.found_tram_lines == 0,
                'Found {} tram lines, expected {}'.format(
                    self.found_tram_lines, self.num_tram_lines
                ),
                )
    
    def validate(self):
        networks = Counter()
        self.found_stations = 0
        unused_stations = set(self.station_ids)
        for rmaster in self.routes.values():
            networks[str(rmaster.network)] += 1
            if not self.overground:
                self.check_return_routes(rmaster)
            route_stations = set()
            for sa in rmaster.stop_areas():
                route_stations.add(sa.transfer or sa.id)
                unused_stations.discard(sa.station.id)
            self.found_stations += len(route_stations)
        if unused_stations:
            self.unused_stations = len(unused_stations)
            self.warn(
                '{} unused stations: {}'.format(
                    self.unused_stations, format_elid_list(unused_stations)
                )
            )
        self.count_unused_entrances()
        self.found_interchanges = len(self.transfers)
        
        if self.overground:
            self.validate_overground_lines()
        else:
            self.validate_lines()
            
            if self.found_stations != self.num_stations:
                msg = 'Found {} stations in routes, expected {}'.format(
                    self.found_stations, self.num_stations
                )
                self.error_if(
                    not (
                            0
                            <= (self.num_stations - self.found_stations)
                            / self.num_stations
                            <= ALLOWED_STATIONS_MISMATCH
                    ),
                    msg,
                )
            
            if self.found_interchanges != self.num_interchanges:
                msg = 'Found {} interchanges, expected {}'.format(self.found_interchanges, self.num_interchanges)
                self.error_if(
                    self.num_interchanges != 0
                    and not (
                            (self.num_interchanges - self.found_interchanges)
                            / self.num_interchanges
                            <= ALLOWED_TRANSFERS_MISMATCH
                    ),
                    msg,
                    )
        
        self.found_networks = len(networks)
        if len(networks) > max(1, len(self.networks)):
            n_str = '; '.join(
                ['{} ({})'.format(k, v) for k, v in networks.items()]
            )
            self.warn('More than one network: {}'.format(n_str))