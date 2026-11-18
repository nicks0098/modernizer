from app.util import fmt


class Counter(object):
    def __init__(self):
        self.data = {}

    def add(self, key):
        if self.data.has_key(key):
            self.data[key] += 1
        else:
            self.data[key] = 1

    def report(self):
        for key, count in self.data.iteritems():
            print fmt(key, count)

    def top(self):
        return sorted(self.data.items(), key=lambda kv: kv[1])[-1]

    def ids(self):
        return [i for i in xrange(len(self.data))]
