class EntityManager:
    def __init__(self):
        self._next_entity_id = 0
        self._entities = set()

    def create_entity(self):
        entity_id = self._next_entity_id
        self._next_entity_id += 1
        self._entities.add(entity_id)
        return entity_id

    def destroy_entity(self, entity_id):
        self._entities.discard(entity_id)
