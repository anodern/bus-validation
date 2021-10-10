
CONSTRUCTION_KEYS = (
    'construction',
    'proposed',
    'construction:railway',
    'proposed:railway',
)

class Route:
    def __init__(self, route_id, relation, city):
        
        self.city = city
        self.element = relation
        self.route_id = route_id
        
        self.type = relation['type']
        self.route = relation['route']
        self.name = relation['name']
        self.ref = relation.get('ref', None)
        self.operator = relation.get('operator', None)
        self.version = relation.get('public_transport:version', None)
        self.route_from = relation.get('from', None)
        self.route_to = relation.get('to', None)
        
        self.official_name = ''
        self.roundtrip = ''
        self.via = ''
        self.fee = ''
        self.charge = ''
        self.stops = []
        
        if self.version is None:
            city.warn('Public transport version is 1, which means the route is an unsorted pile of objects', relation)
        
        if self.ref is None:
            city.warn('Missing ref on a route', relation)

        if self.route_from is None:
            city.warn('Missing "from" on a route', relation)

        if self.route_to is None:
            city.warn('Missing "to" on a route', relation)

    def __len__(self):
        return len(self.stops)

    def __getitem__(self, i):
        return self.stops[i]

    def __iter__(self):
        return iter(self.stops)

    def __repr__(self):
        return (
            'Route(id={}, type={}, ref={}, name={}, network={}, from={}, to={}'
        ).format(
            self.route_id,
            self.type,
            self.ref,
            self.name,
            self.operator,
            self.route_from,
            self.route_to,
        )
        
    @staticmethod
    def is_route(el, modes):
        if el['type'] != 'relation' or el.get('tags', {}).get('type') != 'route':
            return False
        if 'members' not in el:
            return False
        if el['tags'].get('route') not in modes:
            return False
        for k in CONSTRUCTION_KEYS:
            if k in el['tags']:
                return False
        if 'ref' not in el['tags'] and 'name' not in el['tags']:
            return False
        return True

class RouteMaster:
    def __init__(self, ref, relation, city):
        self.relation = relation
        self.city = city

        self.ref = ref
        self.name = ''
        self.official_name = ''
        self.routes = []

    def __repr__(self):
        text = 'RouteMaster(ref={}, count={})'.format(self.ref, len(self.routes))
        for r in self.routes:
            text = text + '\n\t' + str(r)
            
        return text
    