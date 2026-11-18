import unittest

from app.core import Counter


class CounterTest(unittest.TestCase):
    def test_top(self):
        c = Counter()
        c.add("a")
        c.add("a")
        c.add("b")
        self.assertEqual(c.top(), ("a", 2))

    def test_errors(self):
        try:
            raise ValueError, "bad"
        except ValueError, e:
            self.assertEqual(str(e), "bad")

    def test_ids(self):
        c = Counter()
        c.add("x")
        self.assertEqual(c.ids(), [0])
