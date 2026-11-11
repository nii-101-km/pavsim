"""Collect one signal from each connected input for each block invocation.

Packets remain owned by the caller; the executor releases pending packets.
"""


class InputRendezvous:
    def __init__(self, ports):
        ports = tuple(ports)
        if len(set(ports)) != len(ports):
            raise ValueError('An input can have only one connection.')
        self._slots = {port: None for port in ports}

    def put(self, port, packet):
        if port not in self._slots:
            raise ValueError(f'Input {port!r} is not connected.')
        if self._slots[port] is not None:
            raise ValueError(f'Вход {port} уже содержит сигнал; следующий сигнал не принят.')
        self._slots[port] = packet

    def ready(self):
        # Sources are activated explicitly, not repeatedly by an empty barrier.
        return bool(self._slots) and all(value is not None for value in self._slots.values())

    def take(self):
        if not self.ready():
            raise ValueError('Not all connected inputs have received a signal.')
        packets = self._slots.copy()
        self._slots = dict.fromkeys(self._slots)
        return packets

    def waiting_for(self):
        if not any(value is not None for value in self._slots.values()):
            return ()
        return tuple(port for port, value in self._slots.items() if value is None)

    def drain(self):
        for port, packet in self._slots.items():
            if packet is not None:
                self._slots[port] = None
                yield packet
