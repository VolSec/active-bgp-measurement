#!/usr/bin/env python

from __future__ import print_function

import random
import time
import sys
import select
import json
import logging
from collections import OrderedDict
from pprint import pformat
from kafka import KafkaProducer

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
            s.append('as-path [ {{}} ]'.format(' '.join(self.as_set)))
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


def inspect_kafka_message(msg_future):
    # Block for 'synchronous' sends
    try:
        record_metadata = msg_future.get(timeout=10)
        return True
    except KafkaError:
        return False


def run_measurements(exabgp, producer):
    with open('/home/jms/projects/bgp/active-bgp-measurement/framework/experiments/by_degree/by_degree_ases_poisoned.csv', 'w') as f:
        f.write('asn,degree\n')

    asn_to_degree = OrderedDict()
    with open('/home/jms/projects/bgp/active-bgp-measurement/framework/experiments/by_degree/random_sample_asn_to_degree.csv', 'r') as f:
        for i, line in enumerate(f.readlines()):
            if i != 0:
                line = line.rstrip()
                if not line.startswith('#'):
                    line = line.split(',')
                    asn, degree = line[0], line[1]
                    asn_to_degree[asn] = degree

    # Start collector
    normal_prefix = '208.45.214.0/23'
    start_collector = producer.send('exabgp', {'SENT_TIME': int(time.time()),
                                      'ACTION': 'START_COLLECTOR',
                                      'ACTION_PAYLOAD': {'COLLECTOR_ID': 'by-degree-high-to-low',
                                                         'PREFIX': normal_prefix}})
    success = inspect_kafka_message(start_collector)
    if not success:
        sys.exit(1)

    # Send out normal advertisement first, wait 10 minutes
    normal_announcement = Announcement(normal_prefix, 'self')
    exabgp.write(normal_announcement)
    time.sleep(300)

    for asn, degree in asn_to_degree.items():
        modified_announcement = Announcement('208.45.214.0/23', 'self')
        modified_announcement.prepend('3450')
        modified_announcement.prepend(str(asn))
        # L3 will add 3450 on the other end
        # modified_announcement.prepend('3450')
        exabgp.write(modified_announcement)

        with open('/home/jms/projects/bgp/active-bgp-measurement/framework/experiments/by_degree/by_degree_ases_poisoned.csv', 'a') as f:
            f.write('{},{}\n'.format(asn, degree))

        time.sleep(300)

    end_collector = producer.send('exabgp', {'SENT_TIME': int(time.time()),
                                      'ACTION': 'END_COLLECTOR',
                                      'ACTION_PAYLOAD': {'COLLECTOR_ID': 'by-degree-high-to-low'}})

    success = inspect_kafka_message(end_collector)
    if not success:
        sys.exit(1)


def main():
    producer = KafkaProducer(value_serializer=lambda m: json.dumps(m).encode('ascii'))
    exabgp = ExaBGP()
    run_measurements(exabgp, producer)

if __name__ == '__main__':
    main()
