from collections import defaultdict

class ComponentManager:
    def __init__(self):
        self._components = defaultdict(dict)

    def add_component(self, entity_id, component):
        comp_type = type(component)
        self._components[comp_type][entity_id] = component

    def get_component(self, entity_id, comp_type):
        return self._components[comp_type].get(entity_id)

    def get_all(self, comp_type):
        return self._components[comp_type].items()

    def remove_component(self, entity_id, comp_type):
        if entity_id in self._components[comp_type]:
            del self._components[comp_type][entity_id]
