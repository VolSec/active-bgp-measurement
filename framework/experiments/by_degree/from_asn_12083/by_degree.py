#!/usr/bin/env python

from __future__ import print_function

import random
import time
import atexit
import sys
import select
import json
import logging
from collections import OrderedDict
from pprint import pformat

from kafka import KafkaProducer
from rib_client import NLRIClient


def inspect_kafka_message(msg_future):
    # Block for 'synchronous' sends
    try:
        record_metadata = msg_future.get(timeout=10)
        return True
    except KafkaError:
        return False


def run_measurements(producer, port):
    with open('by_degree_ases_poisoned.csv', 'w') as f:
        f.write('asn,degree\n')

    asn_to_degree = OrderedDict()
    with open(str(sys.argv[2]), 'r') as f:
        for i, line in enumerate(f.readlines()):
            if i != 0:
                line = line.rstrip()
                if not line.startswith('#'):
                    line = line.split(',')
                    asn, degree = line[0], line[1]
                    asn_to_degree[asn] = degree

    # Start collector
    normal_prefix = '208.45.215.0/24'
    start_collector = producer.send('exabgp', {'SENT_TIME': int(time.time()),
                                      'ACTION': 'START_COLLECTOR',
                                      'ACTION_PAYLOAD': {'COLLECTOR_ID': 'by-degree-high-to-low-12083-wait40-post-27-degree',
                                                         'PREFIX': normal_prefix}})
    success = inspect_kafka_message(start_collector)
    if not success:
        sys.exit(1)

    # Send out normal advertisement first, wait 10 minutes
    rib_client = NLRIClient('208.45.215.0/24', port=port)
    time.sleep(2400)

    for asn, degree in asn_to_degree.items():
        poison_asns = [asn] + [3450]
        rib_client = NLRIClient('208.45.215.0/24', port=port,
                                as_seq=poison_asns)

        with open('by_degree_ases_poisoned.csv', 'a') as f:
            f.write('{},{}\n'.format(asn, degree))

        time.sleep(2400)


def end_collector_call():
    end_collector = producer.send('exabgp', {'SENT_TIME': int(time.time()),
                                      'ACTION': 'END_COLLECTOR',
                                      'ACTION_PAYLOAD': {'COLLECTOR_ID': 'by-degree-high-to-low-12083-wait40-post-27-degree'}})

    success = inspect_kafka_message(end_collector_call)
    if not success:
        sys.exit(1)


def main():
    if len(sys.argv) < 3:
        print('usage: by_degree.py <RIB_PORT> <ASNS>')
        sys.exit(1)

    producer = KafkaProducer(value_serializer=lambda m: json.dumps(m).encode('ascii'))

    atexit.register(end_collector_call)

    run_measurements(producer, int(sys.argv[1]))

if __name__ == '__main__':
    main()
