#!/usr/bin/env python

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


PREFIX = None
EXP_ID = None
ASNS = None


def inspect_kafka_message(msg_future):
    # Block for 'synchronous' sends
    try:
        record_metadata = msg_future.get(timeout=10)
        return True
    except KafkaError:
        return False


def make_announcement(prefix, wait_time=None, as_seq=None):
    log_message('Making announcement to {} on routers {} and waiting {} seconds for AS SEQ: {}'.format(prefix, router_ports, wait_time, as_seq))

    # Send advertisement
    for router_port in router_ports:
        as_seq_set = None
        if as_seq is not None:
            if isinstance(as_seq, set):
                as_seq_set = as_seq
            elif isinstance(as_seq, int):
                as_seq_set = set()
                as_seq_set.add(as_seq)
            else:
                raise ValueError("AS Seq is not a list or int!")

        if as_seq is not None and append_origin:
            to_append = list(as_seq_set) + [origin]
            rib_client = NLRIClient(prefix, port=router_port, as_seq=to_append)
        elif as_seq is not None and not append_origin:
            rib_client = NLRIClient(prefix, port=router_port, as_seq=list(as_seq_set))
        else:
            rib_client = NLRIClient(prefix, port=router_port)

    time.sleep(wait_time)


def run_measurements(producer, port):
    global EXP_ID
    global ASNS
    global PREFIX

    with open('by_degree_ases_poisoned_{}_{}.csv'.format(EXP_ID, PREFIX), 'w') as f:
        f.write('asn,degree\n')

    asn_to_degree = OrderedDict()
    with open(ASNS, 'r') as f:
        for i, line in enumerate(f.readlines()):
            if i != 0:
                line = line.rstrip()
                if not line.startswith('#'):
                    line = line.split(',')
                    asn, degree = line[0], line[1]
                    asn_to_degree[asn] = degree

    # Start collector
    normal_prefix = PREFIX
    start_collector = producer.send('exabgp', {'SENT_TIME': int(time.time()),
                                      'ACTION': 'START_COLLECTOR',
                                      'ACTION_PAYLOAD': {'COLLECTOR_ID': '{}_{}'.format(EXP_ID, PREFIX),
                                                         'PREFIX': normal_prefix}})
    success = inspect_kafka_message(start_collector)
    if not success:
        sys.exit(1)


    time.sleep(2400)

    for asn, degree in asn_to_degree.items():
        poison_asns = [asn] + [3450]



        with open('by_degree_ases_poisoned_{}_{}.csv'.format(EXP_ID, PREFIX), 'a') as f:
            f.write('{},{}\n'.format(asn, degree))

        time.sleep(2400)


def end_collector_call():
    global EXP_ID
    global PREFIX

    end_collector = producer.send('exabgp', {'SENT_TIME': int(time.time()),
                                      'ACTION': 'END_COLLECTOR',
                                      'ACTION_PAYLOAD': {'COLLECTOR_ID': '{}_{}'.format(EXP_ID, PREFIX)}})

    success = inspect_kafka_message(end_collector_call)
    if not success:
        sys.exit(1)


def main():
    global PREFIX
    global EXP_ID
    global ASNS

    if len(sys.argv) < 4:
        print('usage: by_degree.py <PREFIX> <ASNS> <EXP_ID>')
        sys.exit(1)

    PREFIX = str(sys.argv[1])
    EXP_ID = str(sys.argv[3])
    ASNS = str(sys.argv[2])

    producer = KafkaProducer(value_serializer=lambda m: json.dumps(m).encode('ascii'))

    atexit.register(end_collector_call)

    run_measurements(producer)

if __name__ == '__main__':
    main()
