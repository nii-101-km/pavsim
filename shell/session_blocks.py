"""Per-block session instances and their cooperative shutdown hooks."""


class SessionBlocks:
    """Own every block instance created in this session until it ends."""
    def __init__(self):
        self._instances = []

    def prepare(self, graph, registry):
        from .blocks.catalog import lookup
        prepared = {}
        first = len(self._instances)
        try:
            for node in graph.nodes.values():
                block_type = lookup(node.type, registry)
                factory = getattr(block_type, 'create_session_block', None)
                if factory is None:
                    continue
                block = factory(node.id, node.params)
                if block is None:
                    raise ValueError(f'Блок {node.id}: не удалось создать экземпляр сессии.')
                self._instances.append(block)
                prepared[node.id] = block
            return prepared
        except BaseException:
            created, self._instances = self._instances[first:], self._instances[:first]
            self._call(created, 'request_stop')
            self._call(created, 'close_session')
            raise

    @staticmethod
    def _call(instances, method):
        errors = []
        for block in instances:
            hook = getattr(block, method, None)
            if hook is not None:
                try:
                    hook()
                except Exception as exc:
                    errors.append(str(exc))
        return errors

    def request_stop(self):
        return self._call(self._instances, 'request_stop')

    def close(self):
        instances, self._instances = self._instances, []
        return self._call(instances, 'close_session')
