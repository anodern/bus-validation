
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
        self.name = relation['name']
        self.operator = relation['operator']
        self.version = relation['public_transport:version']
        self.route = relation['route']
        self.route_from = relation['route']
        self.route_to = relation['to']
        self.stops = []
        
        if 'ref' not in relation:
            city.warn('Missing ref on a route', relation)
        self.ref = relation['ref']

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
        self.ref = ref
        self.relation = relation
        self.city = city
        self.name = ''
        self.routes = []

    def __repr__(self):
        text = 'Route(ref={}, name={})'.format(self.ref, len(self.routes))
        for r in self.routes:
            text = text + '\n\t' + str(r)
            
        return text
    