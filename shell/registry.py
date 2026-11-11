"""Registry of available executors."""


class ExecutorRegistry:
    """Registry of available executors."""

    def __init__(self):
        self._executors = {}

    def register(self, executor):
        """Register an executor instance."""
        self._executors[executor.name] = executor

    def get(self, name):
        """Get executor by name, or None if not found."""
        return self._executors.get(name)

    def list(self):
        """List all registered executors with metadata."""
        return [e.describe() for e in self._executors.values()]

    def names(self):
        """Return list of registered executor names."""
        return list(self._executors.keys())

    def __contains__(self, name):
        return name in self._executors
