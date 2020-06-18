#!/usr/bin/env python
from __future__ import print_function

import time
import sys
import select
import json
import logging
from pprint import pformat


class Announcement:
    def __init__(self, route, next_hop, community=[], path=[]):
        self.route = route
        self.next_hop = next_hop
        self.community = community
        self.path = path

    def prepend(self, path):
        if isinstance(path, str) or isinstance(path, int):
            path = [str(path)]
        self.path = path + self.path

    def __str__(self):
        s = ['announce route {} next-hop {}'.format(self.route, self.next_hop)]
        if self.community:
            s.append('community [ {} ]'.format(' '.join(self.community)))
        if self.path:
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


def iter_specificity(exabgp, _range=[24, 32]):
    """Advertise out a range of specific subnets for the prefix"""
    timeout = 300
    normal_announcement = Announcement('208.45.214.0/23',
                                       'self', path=['3450'])

    exabgp.write(normal_announcement)
    time.sleep(600)

    announcements = []
    for subnet in range(_range[0], _range[1] + 1):
        announcement = Announcement('208.45.214.0/{}'.format(subnet),
                                    'self', path=['3450'])
        announcements.append(announcement)

    normal_timeout = 300

    for announcement in announcements:
        rfds, _, _ = select.select([sys.stdin], [], [], timeout)
        if len(rfds) > 0:
            for msg in exabgp.read():
                fprint(pformat(msg), file=sys.stderr)

        exabgp.write(announcement)
        time.sleep(normal_timeout)


def main():
    exabgp = ExaBGP()
    iter_specificity(exabgp)


if __name__ == '__main__':
    main()
