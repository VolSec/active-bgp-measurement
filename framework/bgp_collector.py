"""
    BGPCollector is a class for controlling a BGPStream real-time
    BGP update collector from Apache Kafka.
"""

import time
import inspect
import os
import argparse
import copy
import json
import datetime
from Queue import Queue
from threading import Thread
from pprint import pprint
from multiprocessing import Process

from kafka import KafkaConsumer
from _pybgpstream import BGPStream, BGPRecord, BGPElem


class BGPCollector():
    def __init__(self):
        self.message_queue = Queue()
        self.kafka_consumer = KafkaConsumer(value_deserializer=lambda m: json.loads(m.decode('ascii')),
                                            api_version=(0,10))
        self.kafka_consumer.subscribe('exabgp')

        self.collectors = dict()

    def start(self):
        self.start_listener()
        self.monitor_collectors()

    def process_messages(self, message_queue):
        while True:
            for message in self.kafka_consumer:
                print('Processing message from Kafka: {}'.format(message.value))
                message_queue.put(message.value)
            time.sleep(1)

    def start_listener(self):
        worker = Thread(target=self.process_messages,
                        args=(self.message_queue,))
        worker.setDaemon(True)
        worker.start()

    def process_message(self, message):
        """
            Messages from Kafka are dicts with the following keys:
                SENT_TIME, ACTION, ACTION_PAYLOAD

            The possible ACTIONs are:
                START_COLLECTOR: Start a new collector.
                                  - This ACTION has an ACTION_PAYLOAD containing the
                                  name to for the ID of the new collection instance AND
                                  the prefix to monitor. The two arguments are
                                  seperated by a '-'
                END_COLLECTOR: End the ongoing collector. ACTION_PAYLOAD of of
                                the COLLECTOR_ID or "ALL" if
                                if all collectors should be killed.
        """

        sent_time, action, action_payload = message['SENT_TIME'], message['ACTION'], message['ACTION_PAYLOAD']
        if str(action) == 'START_COLLECTOR':
            collector_id, prefix = action_payload['COLLECTOR_ID'], action_payload['PREFIX']
            self.start_collector(sent_time,
                                 collector_id,
                                 prefix)
        elif str(action) == 'END_COLLECTOR':
            collector_id = action_payload['COLLECTOR_ID']
            if collector_id == "ALL":
                self.end_collector(end_all=True)
            else:
                self.end_collector(collector_id=collector_id)
        else:
            print('Invalid action recieved from Kafka!')

    def monitor_collectors(self):
        print('Monitoring collectors...')
        while True:
            message = self.message_queue.get()
            self.process_message(message)
            self.message_queue.task_done()

    def start_collector(self, start_time, collector_id, prefix):
        full_collector_id = '/opt/bgp/bgpstream_output_{}_{}.txt'.format(start_time, collector_id)
        bgpstream = setup_bgpstream(prefix)

        print('Starting collector with output file {}...'.format(full_collector_id))
        this_collector = Process(target=run_collector,
                                        args=(bgpstream, full_collector_id,))
        this_collector.start()
        self.collectors[collector_id] = this_collector

    def end_collector(self, collector_id=None, end_all=False):
        if len(self.collectors) == 0:
            print('No collectors are currently running that can be ended!')
        elif end_all:
            print('Ending all collectors...')
            temp_collectors = self.collectors
            for this_collector_id, collector in temp_collectors.items():
                print('Ending collector {}...'.format(this_collector_id))
                collector.terminate()
                while True:
                    if not collector.is_alive():
                        print('Ended collector {}.'.format(this_collector_id))
                        del self.collectors[this_collector_id]
                        break
                    time.sleep(0.5)
        elif collector_id is not None:
            print('Ending collector {}...'.format(collector_id))
            collector = self.collectors[str(collector_id)]
            collector.terminate()
            while True:
                if not collector.is_alive():
                    print('Ended collector {}.'.format(collector_id))
                    del self.collectors[collector_id]
                    break
                time.sleep(0.5)
        else:
            print('Invalid options passed to end_collector!')

def setup_bgpstream(prefix):
    # Current time in seconds since the epoch
    epoch_time = int(time.time())
    current_utc_time = datetime.datetime.utcnow().strftime('%Y-%m-%d-%H-%M')

    # Create a new bgpstream instance
    stream = BGPStream()

    # Only get updates
    stream.add_filter('record-type', 'updates')

    # Only get updates from our prefix
    #stream.add_filter('prefix', '208.45.214.0/23')
    stream.add_filter('prefix', prefix)

    # Add data providers
    stream.add_filter('project', 'routeviews')
    stream.add_filter('project', 'ris')

    # Start pulling live
    stream.add_interval_filter(epoch_time, 0)

    return stream

def run_collector(stream, output_file):
    # Start the stream
    stream.start()

    # Create record
    rec = BGPRecord()

    # Collect some general stream stats
    total_records = 0
    total_updates = 0

    # Write to output file
    with open(output_file, 'w') as f:
        # Read in each record at a time
        while (stream.get_next_record(rec)):
            # Print the record information only if it is not a valid record
            if rec.status != "valid":
                print('Recieved invalid record from BGPStream collector {}'.format(rec.collector))
                record_members = []
                for i in inspect.getmembers(rec):
                    # Ignores anything starting with underscore
                    # (that is, private and protected attributes)
                    if not i[0].startswith('_'):
                        # Ignores methods
                        if not inspect.ismethod(i[1]):
                            record_members.append(i)
                print('Invalid record: {}'.format(record_members))
            else:
                elem = rec.get_next_elem()
                while (elem):
                    # Aggregate metadata about new record
                    metadata = dict()
                    metadata['rec_dump_time'] = rec.dump_time
                    metadata['project'] = rec.project
                    metadata['collector'] = rec.collector
                    metadata['rec_type'] = rec.type
                    metadata['rec_time'] = rec.time
                    metadata['status'] = rec.status
                    metadata['elem_type'] = elem.type
                    metadata['elem_time'] = elem.time
                    metadata['peer_address'] = elem.peer_address
                    metadata['peer_asn'] = elem.peer_asn

                    # Update and log stats
                    total_records += 1
                    if elem.type == 'A':
                        total_updates += 1

                    if total_records % 100 == 0:
                        print('Collected {} total records and {} total announcements...'.format(total_records, total_updates))

                    # Build full record and save to file
                    full_record = merge_dicts(metadata, elem.fields)
                    f.write(json.dumps(full_record) + '\n')

                    # Get the next element
                    elem = rec.get_next_elem()

def merge_dicts(x, y):
    z = x.copy()
    z.update(y)
    return z

