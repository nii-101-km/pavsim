import unittest

from shell.flow_tracker import FlowTracker


class FlowTrackerTests(unittest.TestCase):
    def test_multiple_branches_and_cleanup(self):
        published = []
        tracker = FlowTracker(published.append)
        tracker.change('block', '1.1', 'waiting', 1, 'p1')
        tracker.change('block', '1.1', 'waiting', 1, 'p1')
        tracker.change('block', '1.2', 'working', 1)
        self.assertEqual(len(tracker.snapshot()['block']), 3)
        tracker.change('block', '1.1', 'waiting', -1, 'p1')
        self.assertEqual(len(tracker.snapshot()['block']), 2)
        tracker.clear()
        self.assertEqual(published[-1], {})

    def test_absent_identifier_does_not_create_a_badge(self):
        tracker = FlowTracker()
        tracker.change('block', None, 'working', 1)
        self.assertEqual(tracker.snapshot(), {})
