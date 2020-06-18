#!/usr/bin/env python


import time
import json

from kafka import KafkaProducer


def test_msg(msg_future):
    # Block for 'synchronous' sends
    try:
        record_metadata = msg_future.get(timeout=10)
    except KafkaError:
        # Decide what to do if produce request failed...
        print('Kafka error!')
        pass

    # Successful result returns assigned partition and offset
    print('Message topic: {}'.format(record_metadata.topic))
    print('Message partition: {}'.format(record_metadata.partition))
    print('Message offset: {}'.format(record_metadata.offset))


def test_bgp_collector():
    producer = KafkaProducer(value_serializer=lambda m: json.dumps(m).encode('ascii'))

    # Asynchronous by default
    first_end_msg = producer.send('exabgp', {'SENT_TIME': 'test_time0',
                                      'ACTION': 'END_COLLECTOR',
                                                'ACTION_PAYLOAD': {'COLLECTOR_ID': 'ALL'}})
    test_msg(first_end_msg)

    start_msg1 = producer.send('exabgp', {'SENT_TIME': 'test_time1',
                                      'ACTION': 'START_COLLECTOR',
                                      'ACTION_PAYLOAD': {'COLLECTOR_ID': 'collector1',
                                                         'PREFIX':'208.45.214.0/23' }})
    test_msg(start_msg1)

    time.sleep(5)

    end_msg1 = producer.send('exabgp', {'SENT_TIME': 'test_time1',
                                      'ACTION': 'END_COLLECTOR',
                                        'ACTION_PAYLOAD': {'COLLECTOR_ID': 'collector1'}})
    test_msg(end_msg1)

    time.sleep(5)

    start_msg2 = producer.send('exabgp', {'SENT_TIME': 'test_time2',
                                      'ACTION': 'START_COLLECTOR',
                                      'ACTION_PAYLOAD': {'COLLECTOR_ID': 'collector2',
                                                         'PREFIX':'208.45.214.0/23' }})
    start_msg3 = producer.send('exabgp', {'SENT_TIME': 'test_time2',
                                      'ACTION': 'START_COLLECTOR',
                                      'ACTION_PAYLOAD': {'COLLECTOR_ID': 'collector3',
                                                         'PREFIX':'208.45.214.0/23' }})
    test_msg(start_msg2)
    test_msg(start_msg3)

    time.sleep(5)

    last_end_msg = producer.send('exabgp', {'SENT_TIME': 'test_time2',
                                      'ACTION': 'END_COLLECTOR',
                                            'ACTION_PAYLOAD': {'COLLECTOR_ID': 'ALL'}})
    test_msg(last_end_msg)

    time.sleep(500)


if __name__ == '__main__':
    test_bgp_collector()
