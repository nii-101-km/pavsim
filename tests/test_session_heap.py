import unittest
from shell.heap import InvalidReference, SessionHeap, SessionHeaps


class SessionHeapTests(unittest.TestCase):
    def test_three_consumers_reuse_one_object_until_all_are_done(self):
        heap = SessionHeap()
        large = {'data': list(range(1000))}
        first = heap.put(large)
        second, third = heap.fork(first), heap.fork(first)
        self.assertEqual(len({first['value'], second['value'], third['value']}), 3)
        self.assertIs(heap.read(first), large)
        self.assertIs(heap.read(second), large)
        self.assertIs(heap.read(second), large)
        heap.release(first)
        heap.release(second)
        self.assertIs(heap.read(third), large)
        heap.release(third)
        self.assertEqual(len(heap._objects), 0)
        with self.assertRaises(InvalidReference):
            heap.read(third)

    def test_reference_is_session_scoped_and_close_invalidates_it(self):
        left, right = SessionHeap(), SessionHeap()
        reference = left.put('value')
        with self.assertRaises(InvalidReference):
            right.read(reference)
        left.close()
        with self.assertRaises(InvalidReference):
            left.read(reference)

    def test_expiry_and_heartbeat(self):
        clock = [0]
        heaps = SessionHeaps(ttl_seconds=10, clock=lambda: clock[0])
        heap = heaps.create()
        reference = heap.put('value')
        clock[0] = 9
        heaps.touch(heap.session_id)
        clock[0] = 18
        self.assertEqual(heaps.expire(), 0)
        clock[0] = 19
        self.assertEqual(heaps.expire(), 1)
        with self.assertRaises(InvalidReference):
            heap.read(reference)

class NestedStructureTests(unittest.TestCase):
    def test_fork_preserves_flow_ids_on_reference_and_list(self):
        from shell.structures import list_structure, read_list_structure, fork_structure, release_structure
        heap = SessionHeap()
        source = dict(heap.put('payload'), flow_id='1.2')
        packet = dict(list_structure([source]), flow_id='1')
        child = fork_structure(heap, packet)
        self.assertEqual(child['flow_id'], '1')
        self.assertEqual(read_list_structure(child)[0]['flow_id'], '1.2')
        release_structure(heap, packet)
        release_structure(heap, child)
        self.assertFalse(heap._objects)

    def test_list_keeps_separate_reference_for_each_recipient(self):
        from shell.structures import list_structure, read_list_structure, fork_structure, release_structure
        heap = SessionHeap()
        payload = {'large': list(range(1000))}
        source = heap.put(payload)
        packet = list_structure([source, None, {'type': 'float', 'value': '2'}])
        left, right = fork_structure(heap, packet), fork_structure(heap, packet)
        release_structure(heap, packet)
        left_ref = read_list_structure(left)[0]
        right_ref = read_list_structure(right)[0]
        self.assertIs(heap.read(left_ref), payload)
        self.assertIs(heap.read(right_ref), payload)
        release_structure(heap, left)
        self.assertIs(heap.read(right_ref), payload)
        release_structure(heap, right)
        self.assertEqual(len(heap._objects), 0)
