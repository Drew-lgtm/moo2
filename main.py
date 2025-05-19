from ecs.entity_manager import EntityManager
from ecs.component_manager import ComponentManager
from ecs.components import Position, Name, Owner
from ecs.systems import NamePrinterSystem

entity_mgr = EntityManager()
component_mgr = ComponentManager()

# Create entity and add components
e1 = entity_mgr.create_entity()
component_mgr.add_component(e1, Position(100, 200))
component_mgr.add_component(e1, Name("Sol"))
component_mgr.add_component(e1, Owner(empire_id=0))

# Run system
name_printer = NamePrinterSystem(component_mgr)
name_printer.run()
