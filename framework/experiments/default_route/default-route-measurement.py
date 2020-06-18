#!/usr/bin/env python

import datetime
import time
import sys
import json
import subprocess
from .utils import asn_has_probe
from .rib_client import NLRIClient

from kafka import KafkaProducer
import arrow
from ripe.atlas.cousteau import (
  Traceroute,
  AtlasSource,
  AtlasCreateRequest,
  AtlasResultsRequest
)


ATLAS_API_KEY = "REPLACE"
LOG_FILE = None


def inspect_kafka_message(msg_future):
    # Block for 'synchronous' sends
    try:
        # Can get metadata out of this
        msg_future.get(timeout=10)
        return True
    except Exception:
        return False


def get_asn_from_ip(ip):
    split_ip = ip.split('.')
    cymru_encoded_ip = '{}.{}.{}.{}.origin.asn.cymru.com'.format(split_ip[3], split_ip[2], split_ip[1], split_ip[0])
    output = subprocess.check_output(["dig", "+short", cymru_encoded_ip, "TXT"])
    output = output.decode('utf-8').rstrip()
    split_output = output.replace('"', '').split(' | ')
    return split_output[0]


def check_equal_list(lst):
   return lst[1:] == lst[:-1]


def log_message(msg):
    global LOG_FILE

    utcnow = arrow.utcnow().isoformat()
    with open(LOG_FILE, 'a') as f:
        f.write('{} - {}\n'.format(utcnow, msg))


def wait_on_measurement(measurement_id):

    kwargs = {
        "msm_id": int(measurement_id)
    }

    # Wait to get a result
    while True:
        time.sleep(10)
        log_message("Checking measurement status...")
        is_success, results = AtlasResultsRequest(**kwargs).create()

        # Return first (and should be only) result for this ID
        if is_success and len(results) != 0:
            return results[0], False

        if not is_success:
            return _, True


def submit_traceroute(asn):
    traceroute_time = int(time.time())

    traceroute = Traceroute(
        af=4,
        target="208.45.214.0",
        description="{}_{}".format(asn, traceroute_time),
        protocol="ICMP",
    )

    source = AtlasSource(type="asn", value=asn, requested=1)

    atlas_request = AtlasCreateRequest(
        start_time=datetime.datetime.utcnow(),
        key=ATLAS_API_KEY,
        measurements=[traceroute],
        sources=[source],
        is_oneoff=True
    )

    (is_success, response) = atlas_request.create()
    if not is_success:
        return None, traceroute_time

    measurement_id = response["measurements"][0]

    log_message("Measurement ID of {} for ongoing traceroute".format(measurement_id))

    return measurement_id, traceroute_time


def get_immediate_upstream(asn, result, port):
    hop_ips = []
    final_hop_num = 0
    for hop_num, hop_result in enumerate(result):
        final_hop_num += 1
        per_hop_results = hop_result["result"]
        no_result = True
        ips = []
        for per_hop_result in per_hop_results:
            existing_empty = per_hop_result.get("x", None)
            if existing_empty is None:
                no_result = False
                ips.append(per_hop_result["from"])
        if no_result:
            continue

        if check_equal_list(ips):
            hop_ips.append(ips[0])
        else:
            log_message("Different IP for at least one IP for hop {}".format(hop_num))
            hop_ips.append(ips[0])

    log_message("Found {} total valid (non-empty) hops".format(len(hop_ips)))

    hop_asns = []
    for hop_ip in hop_ips:
        hop_asn = get_asn_from_ip(hop_ip)
        if hop_asn == '' or hop_asn is None:
            continue
        hop_asns.append(hop_asn)

    log_message("Getting immediate upstream to poison...")
    immediate_upstream = None
    for hop_asn in hop_asns:
        if hop_asn != asn:
            if hop_asn != '3450' or hop_asn != str(port):
                immediate_upstream = hop_asn
                break
            else:
                log_message('Immediate upstream is 3450 or {}'.format(port))

    return immediate_upstream, hop_asns, final_hop_num


def run_measurements(producer, port):
    with open('edge_asn_measured_{}_{}.csv'.format(port, int(time.time())), 'w') as f:
        f.write('asn,poison_announce_time,normal_traceroute_time,normal_measurement_id,'
                'normal_immediate_upstream,normal_total_hops,normal_asns,poison_traceroute_time,'
                'poison_measurement_id,poison_immediate_upstream,poison_total_hops,poison_asns,success\n')

    to_poison_ases = []
    with open(str(sys.argv[2]), 'r') as f:
        for i, line in enumerate(f.readlines()):
            if i !=0:
                line = line.rstrip()
                if line.startswith("#"):
                    continue
                asn = int(line)
                to_poison_ases.append(asn)

    # Start collector for less specific
    normal_prefix = '208.45.214.0/24'
    start_collector = producer.send('exabgp', {'SENT_TIME': int(time.time()),
                                               'ACTION': 'START_COLLECTOR',
                                               'ACTION_PAYLOAD': {'COLLECTOR_ID': 'default_route_wait_10min',
                                                                  'PREFIX': normal_prefix}})
    success = inspect_kafka_message(start_collector)
    if not success:
        sys.exit(1)

    for asn in to_poison_ases:
        log_message("{}Starting Experiment for AS{}{}".format('-'*10, asn, '-'*10))
        has_probe = asn_has_probe(asn)
        if not has_probe:
            log_message("AS{} does not have a probe!".format(asn))
            continue

        # Make normal announcement
        log_message("Making normal announcement")
        # Send out normal advertisement first, wait 10 minutes
        rib_client = NLRIClient('208.45.214.0/24', port=port)
        time.sleep(600)

        log_message("First traceroute from AS{} to our prefix...".format(asn))

        # Make normal traceroute measurement
        normal_measurement_id, normal_traceroute_time = submit_traceroute(asn)

        # Blocking call
        normal_traceroute_result, err = wait_on_measurement(normal_measurement_id)
        if err:
            log_message("First traceroute from AS{} to our prefix FAILED".format(asn))
            continue
        else:
            log_message("First traceroute from AS{} to our prefix is done".format(asn))

        # Get next hop out that isn't the edge ASN and isn't the AS we sent our advertisement out of
        normal_immediate_upstream, normal_asns, normal_total_hops = get_immediate_upstream(asn, normal_traceroute_result)

        if normal_immediate_upstream is None:
            log_message("Did not find a valid immediate upstream for hop ASNs: {}".format(normal_asns))
            log_message("Going to next edge AS...")
            continue

        log_message("Poisoning out immediate upstream of AS{} for edge AS{}".format(normal_immediate_upstream, asn))

        as_list = [asn] + [3450]
        mod_announce_time = int(time.time())
        rib_client = NLRIClient('208.45.214.0/24', port=port, as_seq=as_list)
        time.sleep(600)

        log_message("Second traceroute from AS{} to our prefix".format(asn))

        # Make poison traceroute measurement
        poison_measurement_id, poison_traceroute_time = submit_traceroute(asn)

        # Blocking call
        poison_traceroute_result, err = wait_on_measurement(poison_measurement_id)
        if err:
            log_message("Second traceroute from AS{} to our prefix FAILED".format(asn))
            continue
        else:
            log_message("Second traceroute from AS{} to our prefix is done".format(asn))

        # Get next hop out that isn't the edge ASN and isn't L3
        poison_immediate_upstream, poison_asns, poison_total_hops = get_immediate_upstream(asn, poison_traceroute_result)

        if poison_immediate_upstream is None:
            log_message("Did not find a valid immediate upstream for hop ASNs: {}".format(poison_asns))
            log_message("Going to next edge AS...")
            continue

        if normal_immediate_upstream != poison_immediate_upstream:
            success = True
            log_message('AS{} used a different immediate upstream after poisonin!'.format(asn))
        else:
            success = False

        with open('edge_asn_measured_{}_{}.csv'.format(port, int(time.time())), 'a') as f:
            result_string = '{},{},{},{},{},{},{},{},{},{},{},{},{}\n'.format(asn,
                                                                      mod_announce_time,
                                                                      normal_traceroute_time,
                                                                      normal_measurement_id,
                                                                      normal_immediate_upstream,
                                                                      normal_total_hops,
                                                                      '-'.join(normal_asns),
                                                                      poison_traceroute_time,
                                                                      poison_measurement_id,
                                                                      poison_immediate_upstream,
                                                                      poison_total_hops,
                                                                      '-'.join(poison_asns),
                                                                      success)
            f.write(result_string)
            log_message(result_string)

    end_collector = producer.send('exabgp', {'SENT_TIME': int(time.time()),
                                             'ACTION': 'END_COLLECTOR',
                                             'ACTION_PAYLOAD': {'COLLECTOR_ID': 'default_route_wait_10min'}})

    success = inspect_kafka_message(end_collector)
    if not success:
        sys.exit(1)


def main():
    global LOG_FILE

    if len(sys.argv) < 2:
        print('usage: long_path.py <RIB_PORT> <ASN_SAMPLE>')
        sys.exit(1)
    log_message('Starting default route measurement!')
    producer = KafkaProducer(value_serializer=lambda m: json.dumps(m).encode('ascii'))
    LOG_FILE = "default_route_log_{}_{}.txt".format(int(sys.argv[1]), int(time.time()))
    run_measurements(producer, int(sys.argv[1]))


if __name__ == '__main__':
    main()
