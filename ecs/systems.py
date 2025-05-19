from ecs.components import Name

class NamePrinterSystem:
    def __init__(self, components):
        self.components = components

    def run(self):
        for entity_id, name in self.components.get_all(Name):
            print(f"Entity {entity_id} is named {name.value}")
