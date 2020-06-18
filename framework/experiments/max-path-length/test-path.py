#!/usr/bin/env python

from __future__ import print_function

import random
import time
import sys
import select
import json
import logging
from pprint import pformat

class Announcement:
    def __init__(self, route, next_hop, community=[], path=[], as_set=[]):
        self.route = route
        self.next_hop = next_hop
        self.community = community
        self.path = path
        self.as_set = as_set

    def prepend(self, path, set_as_set=False):
        if isinstance(path, str) or isinstance(path, int):
            path = [str(path)]
        if set_as_set:
            self.as_set = path + self.as_set
        else:
            self.path = path + self.path

    def __str__(self):
        s = ['announce route {} next-hop {}'.format(self.route, self.next_hop)]
        if self.community:
            s.append('community [ {} ]'.format(' '.join(self.community)))
        if len(self.as_set) != 0:
            s.append('as-path [ ({}) ]'.format(' '.join(self.as_set)))
        elif len(self.as_set) == 0 and self.path:
            s.append('as-path [ {} ]'.format(' '.join(self.path)))
        return ' '.join(s)

class ExaBGP:
    """Convenience API for ExaBGP API to split json messages on input
    Note: Converts sys.stdin to io.BufferedReader in order to do non-blocking IO
    """
    def __init__(self):
        self.ibuf = b''
        self.log = logging.getLogger(__name__)
        #sys.stdin = sys.stdin.detach()

    def read(self):
        data = sys.stdin.read1(8192)
        data = self.ibuf + data
        messages = []
        lines = data.split(b'\n')
        for idx, line in enumerate(lines):
            if line == b'done':
                continue
            try:
                messages.append(json.loads(line.decode()))
            except json.JSONDecodeError as e:
                if idx == len(lines) - 1 and data[-1] != '\n':
                    # Last line not complete
                    self.ibuf = line
                    return messages
                self.log.warn('Failed to decode {!r}: {}'.format(line, e))
        self.ibuf = b''
        return messages

    def write(self, msg):
        fprint(msg)

def fprint(data, file=sys.stdout, end='\n'):
    """Mimics basic print() functionality but flushes file to cause ExaBGP to read it instantly"""
    file.write('{}{}'.format(data, end))
    file.flush()

def iter_as_lengths(exabgp, max_length, to_poison_ases):
    normal_announcement = Announcement('208.45.214.0/23', 'self')

    timeout = 300
    normal_timeout = 600

    exabgp.write(normal_announcement)
    time.sleep(normal_timeout)

    uni_prepend_set = []
    for current_length in range(1, max_length + 1):
        rfds, _, _ = select.select([sys.stdin], [], [], timeout)
        if len(rfds) > 0:
            for msg in exabgp.read():
                fprint(pformat(msg), file=sys.stderr)

        modified_announcement = Announcement('208.45.214.0/23', 'self')
        while True:
            chosen_prepend = random.choice(to_poison_ases)
            if not chosen_prepend in uni_prepend_set:
                uni_prepend_set.append(chosen_prepend)
                for to_prepend in reversed(uni_prepend_set):
                    modified_announcement.prepend(to_prepend, set_as_set=True)
                break
        exabgp.write(modified_announcement)
        time.sleep(timeout)

def main():
    university_ases = []
    with open('/home/jms/projects/bgp/active-bgp-measurement/max-path-length/university-ases-raw.txt', 'r') as f:
        for line in f.readlines():
            university_ases.append(str(line.rstrip()))

    exabgp = ExaBGP()
    iter_as_lengths(exabgp, 500, university_ases)

if __name__ == '__main__':
    main()
