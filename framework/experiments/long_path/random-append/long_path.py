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
from rib_client import NLRIClient


def inspect_kafka_message(msg_future):
    # Block for 'synchronous' sends
    try:
        record_metadata = msg_future.get(timeout=10)
        return True
    except KafkaError:
        return False


def run_measurements(producer, port, asn_file):
    # Number of ASes to prepend
    n = 1
    asns_to_poison = []

    with open(asn_file, 'r') as f:
        for i, line in enumerate(f.readlines()):
            if i != 0:
                line = line.rstrip()
                line = line.split(',')

                asn = int(line[0])
                degree = int(line[1])

                asns_to_poison.append((asn, degree))

    # Start collector
    normal_prefix = '208.45.214.0/24'
    start_collector = producer.send('exabgp', {'SENT_TIME': int(time.time()),
                                      'ACTION': 'START_COLLECTOR',
                                      'ACTION_PAYLOAD': {'COLLECTOR_ID': 'long_path_used_append_0_500_by_5',
                                                         'PREFIX': normal_prefix}})
    success = inspect_kafka_message(start_collector)
    if not success:
        sys.exit(1)

    # Send out normal advertisement first, wait 10 minutes
    rib_client = NLRIClient('208.45.214.0/24', port=port)
    time.sleep(2400)

    #modified_announcement = Announcement('208.45.214.0/{}'.format(prefix), 'self')
    #modified_announcement.prepend('3450')

    with open('{}-length-used-sent-by5.txt'.format(port), 'w') as f:
        for i in range(5, 505, 5):
            sent_time = int(time.time())
            asns_filtered = asns_to_poison[:i]
            asns_filtered_as_only = [x[0] for x in asns_filtered] + [3450]
            rib_client = NLRIClient('208.45.214.0/24', port=port, as_seq=asns_filtered_as_only)
            f.write('{},{},{}\n'.format(sent_time, i, '-'.join(str(x) for x in asns_filtered_as_only)))
            time.sleep(2400)

    #sample = random.sample(asns_to_poison, 5 * n)
    #for asn in sample:
    #    modified_announcement.prepend(str(asn))

    """with open('/home/jms/projects/bgp/active-bgp-measurement/framework/experiments/long_path/sampled_poisoned_ases_{}.txt'.format(5 * n), 'a') as f:
        for asn in sample:
            f.write("{}\n".format(asn))
    """

    end_collector = producer.send('exabgp', {'SENT_TIME': int(time.time()),
                                      'ACTION': 'END_COLLECTOR',
                                      'ACTION_PAYLOAD': {'COLLECTOR_ID': 'long_path_used_append_0_500_by_5'}})

    success = inspect_kafka_message(end_collector)
    if not success:
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print('usage: long_path.py <RIB_PORT> <ASN_SAMPLE>')
        sys.exit(1)
    producer = KafkaProducer(value_serializer=lambda m: json.dumps(m).encode('ascii'))
    run_measurements(producer, int(sys.argv[1]), str(sys.argv[2]))


if __name__ == '__main__':
    main()
