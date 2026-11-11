"""Typed values transported on the shell's connections.

The outer graph transports structures; conversion to numeric values belongs at
an executor boundary, not in the graph itself.
"""
from __future__ import annotations

import math
import re

_FLOAT = re.compile(r'[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\Z')


def float_structure(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Expected a finite number.')
    return {'type': 'float', 'value': str(value)}


def read_float_structure(packet, *, field='value'):
    if not isinstance(packet, dict) or packet.get('type') != 'float' or not isinstance(packet.get('value'), str):
        raise ValueError(f'{field}: expected a float structure with a text value.')
    text = packet['value']
    if not _FLOAT.fullmatch(text):
        raise ValueError(f'{field}: invalid float {text!r}; use a decimal point.')
    number = float(text)
    if not math.isfinite(number):
        raise ValueError(f'{field}: expected a finite number.')
    return number


def list_structure(items):
    """Wrap ordered structures as JSON text, retaining empty positions."""
    import json
    if not isinstance(items, list):
        raise ValueError('List structure requires a list.')
    for item in items:
        if item is not None:
            validate_structure(item)
    return {'type': 'list', 'value': json.dumps(items, ensure_ascii=False, separators=(',', ':'))}


def read_list_structure(packet):
    import json
    validate_structure(packet)
    if packet['type'] != 'list':
        raise ValueError('Expected a list structure.')
    try:
        items = json.loads(packet['value'])
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid list structure JSON.') from exc
    if not isinstance(items, list):
        raise ValueError('List structure value must encode a list.')
    for item in items:
        if item is not None:
            validate_structure(item)
    return items


def validate_structure(packet):
    if not isinstance(packet, dict) or not isinstance(packet.get('type'), str) or not isinstance(packet.get('value'), str):
        raise ValueError('Expected a structure with text type and value.')
    return packet


def fork_structure(heap, packet):
    """Give a consumer its own leases, including references inside lists."""
    validate_structure(packet)
    acquired = []
    def fork(item):
        if item is None:
            return None
        if item['type'] == 'object_ref':
            ref = heap.fork(item)
            ref.update({key: value for key, value in item.items() if key not in ('type', 'value')})
            acquired.append(ref)
            return ref
        if item['type'] == 'list':
            result = list_structure([fork(child) for child in read_list_structure(item)])
            result.update({key: value for key, value in item.items() if key not in ('type', 'value')})
            return result
        return dict(item)
    try:
        return fork(packet)
    except BaseException:
        for ref in reversed(acquired):
            heap.release(ref)
        raise


def release_structure(heap, packet):
    """Release all leases owned by a structure, including nested lists."""
    validate_structure(packet)
    if packet['type'] == 'object_ref':
        heap.release(packet)
    elif packet['type'] == 'list':
        for item in read_list_structure(packet):
            if item is not None:
                release_structure(heap, item)


def structure_references(packet):
    """Return each lease token present in a possibly nested structure once."""
    validate_structure(packet)
    if packet['type'] == 'object_ref':
        return {packet['value']: packet}
    refs = {}
    if packet['type'] == 'list':
        for item in read_list_structure(packet):
            if item is not None:
                refs.update(structure_references(item))
    return refs
