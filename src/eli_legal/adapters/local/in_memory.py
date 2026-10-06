class InMemoryRepository:
    def __init__(self, id_attr: str) -> None:
        self.id_attr = id_attr
        self.items = {}

    def put(self, obj) -> None:
        self.items[getattr(obj, self.id_attr)] = obj

    def get(self, object_id: str):
        return self.items.get(object_id)
