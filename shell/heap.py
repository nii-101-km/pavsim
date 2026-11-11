"""Temporary per-session objects and independently releasable references.

The heap never persists data. Object references are leases; reading does not
consume a lease. Callers must treat objects as immutable after insertion.
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field


class InvalidReference(ValueError):
    pass


@dataclass
class _Object:
    value: object
    leases: set[str] = field(default_factory=set)


class SessionHeap:
    def __init__(self, session_id=None):
        self.session_id = session_id or secrets.token_urlsafe(24)
        self._objects: dict[str, _Object] = {}
        self._references: dict[str, str] = {}
        self._lock = threading.RLock()
        self._closed = False

    def _ensure_open(self):
        if self._closed:
            raise InvalidReference('Session has ended.')

    def put(self, value):
        with self._lock:
            self._ensure_open()
            object_id = secrets.token_urlsafe(24)
            self._objects[object_id] = _Object(value)
            return self._new_reference(object_id)

    def _new_reference(self, object_id):
        token = secrets.token_urlsafe(24)
        reference = f'session:{self.session_id}/ref:{token}'
        self._references[reference] = object_id
        self._objects[object_id].leases.add(reference)
        return {'type': 'object_ref', 'value': reference}

    def _find(self, packet):
        self._ensure_open()
        if not isinstance(packet, dict) or packet.get('type') != 'object_ref' or not isinstance(packet.get('value'), str):
            raise InvalidReference('Expected an object reference.')
        reference = packet['value']
        object_id = self._references.get(reference)
        if object_id is None:
            raise InvalidReference('Object reference is not valid in this session or has been released.')
        return reference, object_id

    def read(self, packet):
        with self._lock:
            _, object_id = self._find(packet)
            return self._objects[object_id].value

    def fork(self, packet):
        with self._lock:
            _, object_id = self._find(packet)
            return self._new_reference(object_id)

    def release(self, packet):
        with self._lock:
            reference, object_id = self._find(packet)
            del self._references[reference]
            obj = self._objects[object_id]
            obj.leases.remove(reference)
            if not obj.leases:
                del self._objects[object_id]

    def close(self):
        with self._lock:
            self._references.clear()
            self._objects.clear()
            self._closed = True

    def block_scope(self):
        return BlockHeapScope(self)


class BlockHeapScope:
    """Track leases created by one block, including on an exception."""
    def __init__(self, heap):
        self.heap = heap
        self.owned = {}

    def put(self, value):
        ref = self.heap.put(value)
        self.owned[ref['value']] = ref
        return ref

    def fork(self, ref):
        result = self.heap.fork(ref)
        self.owned[result['value']] = result
        return result

    def read(self, ref):
        return self.heap.read(ref)

    def release(self, ref):
        self.heap.release(ref)
        self.owned.pop(ref['value'], None)

    def close(self):
        for ref in list(self.owned.values()):
            self.heap.release(ref)
        self.owned.clear()


class SessionHeaps:
    """Tracks active sessions; callers schedule expiry and send heartbeats."""
    def __init__(self, ttl_seconds=1800, clock=time.monotonic):
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._sessions = {}
        self._lock = threading.RLock()

    def create(self):
        with self._lock:
            heap = SessionHeap()
            self._sessions[heap.session_id] = (heap, self.clock())
            return heap

    def touch(self, session_id):
        with self._lock:
            self.expire()
            if session_id not in self._sessions:
                raise InvalidReference('Session is missing or has expired.')
            heap, _ = self._sessions[session_id]
            self._sessions[session_id] = (heap, self.clock())
            return heap

    def close(self, session_id):
        with self._lock:
            entry = self._sessions.pop(session_id, None)
            if entry:
                entry[0].close()

    def expire(self):
        with self._lock:
            now = self.clock()
            expired = [sid for sid, (_, touched) in self._sessions.items() if now - touched >= self.ttl_seconds]
            for sid in expired:
                self.close(sid)
            return len(expired)
