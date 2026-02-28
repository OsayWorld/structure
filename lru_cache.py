from collections import OrderedDict
from typing import Any, Optional


class LRUCache:
    def __init__(self, max_items: int = 20):
        self.max_items = max_items
        self._data = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def set(self, key: str, value: Any):
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self.max_items:
            self._data.popitem(last=False)

    def clear(self):
        self._data.clear()
