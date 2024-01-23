#!/usr/bin/env python
"""
Python's OrderedDict is an ideal data structure
to create an LRU cache
"""
from collections import OrderedDict


# to be replaced with redis later
# Borrowed from https://gist.github.com/damzam/4b0812c997e91f1bed17
class LRUCache:
    def __init__(self, max_length=100000):
        self.cache = OrderedDict()
        self.max_length = max_length

    def __setitem__(self, key, value):
        if key in self.cache:
            self.cache.pop(key)
        self.cache[key] = value
        if len(self.cache) > self.max_length:
            self.cache.popitem(last=False)

    def __getitem__(self, key):
        if key in self.cache:
            value = self.cache.pop(key)
            self.cache[key] = value
            return value
        else:
            raise KeyError

    def __contains__(self, key):
        return key in self.cache
