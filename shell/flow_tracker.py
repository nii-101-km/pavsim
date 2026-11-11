"""Track visible instances of flows at blocks without controlling routing."""
from collections import Counter


class FlowTracker:
    def __init__(self, publish=None):
        self._counts = Counter()
        self._publish = publish

    def change(self, block, flow_id, state, delta, port=None):
        if not isinstance(flow_id, str) or not flow_id:
            return
        key = (str(block), flow_id, state, port)
        self._counts[key] += delta
        if self._counts[key] <= 0:
            del self._counts[key]
        if self._publish:
            self._publish(self.snapshot())

    def snapshot(self):
        blocks = {}
        for (block, flow_id, state, port), count in sorted(self._counts.items(), key=lambda item: str(item[0])):
            blocks.setdefault(block, []).extend({'flow_id': flow_id, 'state': state, 'port': port} for _ in range(count))
        return blocks

    def clear(self):
        self._counts.clear()
        if self._publish:
            self._publish({})
