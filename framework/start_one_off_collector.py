import time
import json
import sys

from kafka import KafkaProducer


def test_msg(msg_future):
    # Block for 'synchronous' sends
    try:
        record_metadata = msg_future.get(timeout=10)
        # Successful result returns assigned partition and offset
        print('Message topic: {}'.format(record_metadata.topic))
        print('Message partition: {}'.format(record_metadata.partition))
        print('Message offset: {}'.format(record_metadata.offset))
    except Exception as e:
        # Decide what to do if produce request failed...
        print('Kafka error: {}'.format(e))
        pass



def start():
    if len(sys.argv) < 3:
        print('usage: start_one_off_collector.py <ID> <PREFIX>')

    collector_id = str(sys.argv[1])
    prefix = str(sys.argv[2])

    producer = KafkaProducer(value_serializer=lambda m: json.dumps(m).encode('ascii'))

    start_msg = producer.send('exabgp', {'SENT_TIME': int(time.time()),
                                        'ACTION': 'START_COLLECTOR',
                                        'ACTION_PAYLOAD': {'COLLECTOR_ID': collector_id,
                                                            'PREFIX': prefix }})
    test_msg(start_msg)

    while True:
        try:
            time.sleep(1)
        except (SystemExit, KeyboardInterrupt) as e:
            end_msg = producer.send('exabgp', {'SENT_TIME': int(time.time()),
                                            'ACTION': 'END_COLLECTOR',
                                                'ACTION_PAYLOAD': {'COLLECTOR_ID': collector_id }})
            test_msg(end_msg)
            break



if __name__ == '__main__':
    start()
