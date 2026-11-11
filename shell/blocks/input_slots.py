"""Input state for blocks that need one signal on each connected input."""
from ..rendezvous import InputRendezvous


class InputSlots:
    def __init__(self, ports):
        self._signals = InputRendezvous(ports)

    def receive(self, port, packet):
        self._signals.put(port, packet)
        return self._signals.take() if self._signals.ready() else None

    def waiting_for(self):
        return self._signals.waiting_for()

    def drain(self):
        return self._signals.drain()


class ConnectedInputs:
    """Block policy: collect one signal on each connected buffered input."""
    @staticmethod
    def create_input_state(ports):
        return InputSlots(ports)
