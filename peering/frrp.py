#!/usr/bin/env python

import datetime
import time
import atexit
import sys
import json
import subprocess
import itertools
from collections import deque, defaultdict, namedtuple
from utils import asn_has_probe, find_probes_by_asn

from kafka import KafkaProducer
from boltons.setutils import IndexedSet
from boltons.iterutils import pairwise
from boltons.fileutils import mkdir_p
import networkx as nx
from networkx.drawing.nx_agraph import graphviz_layout, to_agraph
import pygraphviz as pgv
import arrow
from ripe.atlas.cousteau import (
  Traceroute,
  AtlasSource,
  AtlasCreateRequest,
  AtlasResultsRequest,
  Measurement
)


ATLAS_API_KEY = "48250457-f7b0-4ef6-88c5-a9140c80c1f0"
GENERAL_LOG_FILE = None
DR_LOG_FILE = None
FRRP_LOG_FILE = None
MUX = None
EXP_ID = None
producer = None
PREFIX = None
CONST_WAIT_TIME = None

class AS:
    def __init__(self, asn):
        self.asn = asn
        self.preferred = None
        self.preferences = []
        self.visited = False
        self.degree = None
        self.rtts = []
        self.poison_cache = None

    def set_degree(self, degree):
        self.degree = degree

    def set_visited(self):
        self.visited = True

    def set_rtt(self, rtt):
        self.rtts.append(rtt)

    def set_preferred(self, preferred):
        self.preferred = preferred

    def add_preference(self, preference):
        if preference not in self.preferences:
            self.preferences.append(preference)

    def add_poison_cache(self, poison_cache):
        self.poison_cache = poison_cache

    def __repr__(self):
        return 'AS{}'.format(self.asn)

    def __hash__(self):
        return hash(self.asn)

    def __eq__(self, other):
        return self.asn == other.asn


class PoisonCache:
    def __init__(self):
        self.__cache = dict()

    @staticmethod
    def get_poison_id(poisons):
        return ",".join([str(x) for x in sorted(poisons)])

    def add_poison_set(self, poisons, path, rtts):
        self.__cache[self.get_poison_id(poisons)] = (path, get_kv_string(rtts))

    def get_path(self, poisons):
        existing = self.__cache.get(self.get_poison_id(poisons), None)
        if existing:
            return True
        else:
            return False


def get_kv_string(d):
    lst = []
    for k, v in d.items():
        lst.append('{}-{}'.format(k, v))
    return lst


def inspect_kafka_message(msg_future):
    # Block for 'synchronous' sends
    try:
        # Can get metadata out of this
        msg_future.get(timeout=10)
        return True
    except Exception:
        return False


def get_asn_from_ip(ip):
    global PREFIX

    prefix_no_subnet = str(PREFIX.split('/')[0])
    o1, o2, o3, o4 = prefix_no_subnet.split('.')
    prefix_loopback = "{}.{}.{}.1".format(o1, o2, o3)

    if ip == prefix_loopback:
        return 47065

    split_ip = ip.split('.')
    cymru_encoded_ip = '{}.{}.{}.{}.origin.asn.cymru.com'.format(split_ip[3], split_ip[2], split_ip[1], split_ip[0])
    output = subprocess.check_output(["dig", "+short", cymru_encoded_ip, "TXT"])
    output = output.decode('utf-8').rstrip()
    split_output = output.replace('"', '').split(' | ')
    if split_output[0] is None or split_output[0] == '':
        return None
    else:
        as_string = split_output[0]
        num_ases = len(as_string.split(' '))
        if num_ases == 1:
            return int(as_string)
        else:
            return int(as_string.split(' ')[0])


def check_equal_list(lst):
   return lst[1:] == lst[:-1]


def log_message(msg):
    global GENERAL_LOG_FILE

    utcnow = arrow.utcnow().isoformat()
    with open(GENERAL_LOG_FILE, 'a') as f:
        f.write('{} - {}\n'.format(utcnow, msg))
        print('{} - {}'.format(utcnow, msg))


def wait_on_measurement(measurement_id):

    kwargs = {
        "msm_id": int(measurement_id)
    }

    log_message("Checking measurement status...")

    # Wait to get a result
    i = 0
    num_checks = 50
    while True:
        is_success, results = AtlasResultsRequest(**kwargs).create()

        m = Measurement(id=measurement_id)

        if "No suitable probes" in m.status:
            log_message("No suitable probes")
            return None, True

        # Return first (and should be only) result for this ID
        if is_success and len(results) != 0:
            return results[0], False

        if not is_success:
            log_message("Failed results: {}".format(results))
            if results is not None:
                if len(results) == 0:
                    log_message("ATLAS ResultsRequest returned unsuccessful and results array is empty for try {}".format(i))
            return None, True

        time.sleep(20)
        i += 1

        if i == num_checks:
            log_message("ATLAS measurement did not finish after {} checks over {} seconds with status: {}".format(str(num_checks), str(num_checks*10), m.status))
            return None, True


def submit_traceroute(asn, probe):
    global PREFIX

    traceroute_time = int(time.time())

    prefix_no_subnet = str(PREFIX.split('/')[0])
    o1, o2, o3, o4 = prefix_no_subnet.split('.')
    prefix_loopback = "{}.{}.{}.1".format(o1, o2, o3)
    traceroute = Traceroute(
        af=4,
        target=prefix_loopback,
        description="{}_{}_{}".format(asn, traceroute_time, "{}".format(prefix_no_subnet)),
        protocol="TCP",
        port=39876,
        max_hops=60
    )

    source = AtlasSource(type="probes", value=str(probe), requested=1)

    atlas_request = AtlasCreateRequest(
        start_time=datetime.datetime.utcnow(),
        key=ATLAS_API_KEY,
        measurements=[traceroute],
        sources=[source],
        is_oneoff=True
    )

    (is_success, response) = atlas_request.create()
    if not is_success:
        response = str(response)

        log_message("Traceroute failed: {}".format(response))

        # Handle probe not found in ASN
        if "Your selected ASN is not covered by our network." in response:
            return -1, traceroute_time
        # Handle all other cases
        else:
            return None, traceroute_time

    measurement_id = response["measurements"][0]

    log_message("Measurement ID of {} for ongoing traceroute".format(measurement_id))

    return measurement_id, traceroute_time


def get_traceroute_path(atlas_src, result):
    global PREFIX

    hop_ips = []
    hop_avg_rtts = []

    # Get the IPs from the traceroute
    success = False
    num_hops = len(result)
    for hop_num, hop_result in enumerate(result):
        per_hop_results = hop_result["result"]
        no_result = True
        ips = []
        rtts = []
        for per_hop_result in per_hop_results:
            rtt_exists = per_hop_result.get("rtt", None)
            from_exists = per_hop_result.get("from", None)
            if rtt_exists and from_exists:
                no_result = False
                rtts.append(per_hop_result["rtt"])
                ips.append(per_hop_result["from"])
                if (hop_num + 1) == num_hops:
                    success = True

        if no_result:
            continue

        if check_equal_list(ips):
            hop_ips.append(ips[0])
        else:
            log_message("Different IP for at least one IP for hop {}".format(hop_num))
            hop_ips.append(ips[0])

        avg_rtt = sum(rtts) / len(rtts)
        hop_avg_rtts.append(avg_rtt)

    log_message("Found {} total valid (non-empty) hops".format(len(hop_ips)))

    # Get the ASNs for each IP from Team Cymru
    hop_asns = IndexedSet()
    hop_rtts = dict()
    for hop_ip, hop_rtt in zip(hop_ips, hop_avg_rtts):
        hop_asn = get_asn_from_ip(hop_ip)
        if hop_asn:
            hop_asns.add(hop_asn)
            hop_rtts[hop_asn] = hop_rtt

    if len(hop_asns) != 0:
        # Deal with the first AS not resolving in some cases
        corrected_path = False
        revised_hop_asns = IndexedSet()
        revised_hop_rtts = dict()
        if hop_asns[0] != atlas_src.asn:
            revised_hop_asns.add(atlas_src.asn)
            revised_hop_rtts[atlas_src.asn] = 0.0
            for hop_asn in hop_asns:
                revised_hop_asns.add(hop_asn)
                revised_hop_rtts[hop_asn] = hop_rtts[hop_asn]
            corrected_path = True

        if corrected_path:
            hop_asns = revised_hop_asns
            hop_rtts = revised_hop_rtts

        log_message("Found path: {}".format("->".join(list([str(x) for x in hop_asns]))))
    else:
        success = False

    return hop_asns, num_hops, hop_rtts, success


def parse_source_as_file(filename):
    # Parse the source AS file (where we send traceroutes from)
    source_ases = []
    with open(str(filename), 'r') as f:
        for i, line in enumerate(f.readlines()):
            if i != 0:
                line = line.rstrip()
                if line.startswith("#"):
                    continue
                line = line.split(',')
                asn = int(line[0])
                degree = int(line[1])
                source_ases.append((asn, degree))
    return source_ases


def start_collector(producer, prefix, collector_id):
    # Start the BGP update collector
    start_collector = producer.send('exabgp', {'SENT_TIME': int(time.time()),
                                               'ACTION': 'START_COLLECTOR',
                                               'ACTION_PAYLOAD': {'COLLECTOR_ID': collector_id,
                                                                  'PREFIX': prefix}})
    success = inspect_kafka_message(start_collector)
    if not success:
        sys.exit(1)


def end_collector(producer, collector_id):
    # End the BGP update collector
    end_collector = producer.send('exabgp', {'SENT_TIME': int(time.time()),
                                             'ACTION': 'END_COLLECTOR',
                                             'ACTION_PAYLOAD': {'COLLECTOR_ID': collector_id}})

    success = inspect_kafka_message(end_collector)
    if not success:
        sys.exit(1)


def make_announcement(prefix, _mux, wait_time=None, as_seq=None, origin=47065):
    log_message('Making announcement to {} to mux {} and waiting {} seconds for AS SEQ: {}'.format(prefix, _mux, wait_time, as_seq))

    # Send advertisement
    as_seq_set = None
    if as_seq is not None:
        if isinstance(as_seq, set):
            as_seq_set = as_seq
        elif isinstance(as_seq, int):
            as_seq_set = set()
            as_seq_set.add(as_seq)
        else:
            raise ValueError("AS Seq is not a list or int!")

    try:
        if as_seq is not None:
            args = ["./peering", "prefix", "announce", "-m", "{}".format(_mux), "-p",
             '"{}"'.format(" ".join([str(x) for x in as_seq_set])),
             "{}".format(prefix)]
            log_message("Calling PEERING: {}".format(args))
            subprocess.run(args, check=True)
        else:
            args = ["./peering", "prefix", "announce", "-m", "{}".format(_mux),
                            "{}".format(prefix)]
            log_message("Calling PEERING: {}".format(args))
            subprocess.run(args, check=True)
    except subprocess.CalledProcessError as e:
        log_message("Error calling PEERING: {}".format(e))
        sys.exit(1)

    time.sleep(wait_time)


def write_default_route_entry(entry):
    global DR_LOG_FILE

    with open(DR_LOG_FILE, 'a') as f:
        f.write(entry + '\n')


def write_frrp_entry(entry):
    global FRRP_LOG_FILE

    with open(FRRP_LOG_FILE, 'a') as f:
        f.write(entry + '\n')


def draw_graph(graph, name):
    g = to_agraph(graph)
    g.layout('dot')
    g.draw('{}-graph.png'.format(name))


def add_path(graph, result, atlas_src, measurement_id, poisons=None, first=False):
    new_path = False
    path_asns, _, path_rtts, success = get_traceroute_path(atlas_src, result['result'])
    if not success:
        log_message("Lost connectivity! Traceroute failed")
        if poisons is None:
            poisons = set()
        write_frrp_entry("2|src,{},atlas,{},poisons,[{}],path,[{}],rtts,[{}]".format(atlas_src.asn, measurement_id, ",".join(list([str(x) for x in poisons])),
                                                                                  ",".join([str(x) for x in path_asns]),
                                                                                  ",".join(list([str(x) for x in get_kv_string(path_rtts)]))))
        return None, None, None, False

    for lhs_asn, rhs_asn in pairwise(path_asns):
        lhs_asn_rtt = path_rtts.get(lhs_asn, None)
        rhs_asn_rtt = path_rtts.get(rhs_asn, None)

        lhs_as, rhs_as = AS(lhs_asn), AS(rhs_asn)

        if lhs_asn_rtt:
            lhs_as.set_rtt(lhs_asn_rtt)
        if rhs_asn_rtt:
            rhs_as.set_rtt(rhs_asn_rtt)

        lhs_as.add_preference(rhs_as)
        if first:
            lhs_as.set_preferred(rhs_as)

        if graph.has_edge(lhs_as, rhs_as):
            continue
        else:
            new_path = True
            graph.add_edge(lhs_as, rhs_as)

    log_message("Current total observed ASes: {}".format(str(graph.number_of_nodes())))

    return new_path, path_asns, path_rtts, False


def measure_single_source(graph, atlas_src, path=None, working_probe=None, poison_cache=None, poisons=None, probes=None, first=False):
    global PREFIX
    global CONST_WAIT_TIME
    global MUX

    if poisons is None:
        poisons = set()

    if not path:
        probe_worked = False
        working_probe = None
        for probe in probes:
            # Measure this path
            measurement_id, traceroute_time = submit_traceroute(atlas_src.asn, probe)
            if measurement_id is None:
                return -3
            elif measurement_id == -1:
                # For some reason, RIPE told us a probe is in this AS, but the
                # traceroute still failed
                return -1

            traceroute_result, err = wait_on_measurement(measurement_id)
            if err:
                continue
            else:
                probe_worked = True
                working_probe = probe
                break

        if not probe_worked:
            return -2

        # Get current path
        is_new_path, path_asns, path_rtts, lost_connectivity = add_path(graph, traceroute_result, atlas_src, measurement_id, poisons=poisons, first=first)
        if not is_new_path:
            return
        else:
            poison_cache.add_poison_set(poisons, path_asns, path_rtts)
            write_frrp_entry("0|src,{},atlas,{},poisons,[{}],path,[{}],rtts,[{}]".format(atlas_src.asn, measurement_id, ",".join(list([str(x) for x in poisons])),
                                                                                    ",".join([str(x) for x in path_asns]),
                                                                                    ",".join(list([str(x) for x in get_kv_string(path_rtts)]))))
        path = path_asns

    for current_path_asn in path:
        if current_path_asn in [int(atlas_src.asn), 47065]:
            log_message("Can't poison AS {}! Moving on.".format(current_path_asn))
            continue

        if (len(poisons) + 1) > 3:
            write_frrp_entry("3|src,{},msg,no_more_poisons".format(atlas_src.asn))
            continue

        # Poison current AS plus other needed poisons to get where we are
        current_poison_set = poisons | {current_path_asn}

        existing = poison_cache.get_path(current_poison_set)
        if existing:
            log_message("This poison set ({}) has already been measured, moving on...".format(",".join(list([str(x) for x in current_poison_set]))))
            continue

        make_announcement(PREFIX, MUX, CONST_WAIT_TIME, as_seq=current_poison_set)

        # Measure new path
        measurement_id, traceroute_time = submit_traceroute(atlas_src.asn, working_probe)

        # If failed, quit immediately
        if measurement_id is None or measurement_id == -1:
            return

        traceroute_result, err = wait_on_measurement(measurement_id)
        if err:
            log_message("Traceroute failed, moving on...")
            continue

        # Check if this is a new path
        is_new_path, poisoned_path_asns, poisoned_path_rtts, lost_connectivity = add_path(graph, traceroute_result, atlas_src, measurement_id, poisons=current_poison_set, first=False)
        if not is_new_path:
            log_message("New path NOT found, moving on...")
            continue
        else:
            poison_cache.add_poison_set(current_poison_set, poisoned_path_asns, poisoned_path_rtts)
            write_frrp_entry("0|src,{},atlas,{},poisons,[{}],path,[{}],rtts,[{}]".format(atlas_src.asn, measurement_id, ",".join(list([str(x) for x in current_poison_set])),
                                                                             ",".join(list([str(x) for x in poisoned_path_asns])),
                                                                             ",".join(list([str(x) for x in get_kv_string(poisoned_path_rtts)]))))

        # Recursive call
        log_message("New path WAS found, calling measurement again")
        _ = measure_single_source(graph, atlas_src, poison_cache=poison_cache, poisons=current_poison_set, probes=probes, path=poisoned_path_asns, working_probe=working_probe, first=False)


def run_measurements(producer, source_as_file, exp_start):
    global DR_LOG_FILE
    global GENERAL_LOG_FILE
    global FRRP_LOG_FILE
    global EXP_ID
    global PREFIX
    global MUX
    global CONST_WAIT_TIME

    with open(DR_LOG_FILE, 'w') as f:
        f.write('# Entry formats\n')
        f.write('# Error:       -1|src,asn,msg,err_msg\n')
        f.write('# DR Entry:     0|asn,degree,has_default_route\n')

    with open(FRRP_LOG_FILE, 'w') as f:
        f.write('# Entry formats\n')
        f.write('# Error:              -1|src,asn,msg,err_msg\n')
        f.write('# Final Graph:         1|src,asn,graph_path,measured_graph_file\n')
        f.write('# FRRP Result:         0|src,asn,atlas,m_id,oisons,[poison_set],path,[as-path]\n')
        f.write('# Lost Connectivity:   2|src,asn,atlas,m_id,poisons,[poison_set],path,[as-path]\n')
        f.write("# No More Poisons      3|src,asn,msg,no_more_poisons\n")

    source_ases = parse_source_as_file(source_as_file)

    start_collector(producer, PREFIX, '{}_{}'.format(EXP_ID, PREFIX))

    for source_asn, source_asn_degree in source_ases:
        log_message("{}Starting Experiment for AS{}{}".format('-'*10, source_asn, '-'*10))

        all_probes = find_probes_by_asn(source_asn)
        if not all_probes or len(all_probes) == 0:
            log_message("AS{} does not have a stable probe!".format(source_asn))
            write_frrp_entry("-1|src,{},msg,no_stable_probe".format(source_asn))
            write_default_route_entry("-1|src,{},msg,no_stable_probe".format(source_asn))
            continue

        src_graph = nx.DiGraph()
        source_as = AS(source_asn)
        source_as.set_degree(source_asn_degree)

        # Add ATLAS AS, WoW, and UTK
        src_graph.add_node(source_as)

        make_announcement(PREFIX, MUX, CONST_WAIT_TIME)

        poison_cache = PoisonCache()
        err = measure_single_source(src_graph, source_as, poison_cache=poison_cache, probes=all_probes, first=True)
        source_as.add_poison_cache(poison_cache)

        if err == -1:
            log_message("ATLAS AS {} returns error when trying to traceroute...moving on.".format(source_asn))
            with open('misnomer_atlas_ases.txt', 'a') as f:
                f.write('{}\n'.format(source_asn))
            write_frrp_entry("-1|src,{},msg,atlas_source_traceroute_error".format(source_asn))
            write_default_route_entry("-1|src,{},msg,atlas_source_traceroute_error".format(source_asn))
            continue
        elif err == -2:
            log_message("ATLAS AS {} returns empty response.".format(source_asn))
            with open('rerun_atlas_ases.txt', 'a') as f:
                f.write('{}\n'.format(source_asn))
            write_frrp_entry("-1|src,{},msg,atlas_source_empty_response".format(source_asn))
            write_default_route_entry("-1|src,{},msg,atlas_source_empty_response".format(source_asn))
            continue

        has_default_route = src_graph.out_degree(source_as) <= 1
        log_message("ATLAS AS {} has a default route: {}".format(source_asn, has_default_route))
        write_default_route_entry('0|{},{},{}'.format(source_asn, source_as.degree, has_default_route))

        draw_graph(src_graph, 'graph_results/atlas-as-{}-{}-{}-measured-graph'.format(source_asn, exp_start, EXP_ID))

        gpickle_name = 'graph_results/atlas-as-{}-{}-{}-measured-graph.gpickle'.format(source_asn, exp_start, EXP_ID)
        nx.write_gpickle(src_graph, gpickle_name)
        write_frrp_entry('1|src,{},graph_path,{}'.format(source_asn, gpickle_name))


def end_collector_call():
    global EXP_ID
    global producer
    end_collector(producer, '{}'.format(EXP_ID))


def main():
    global DR_LOG_FILE
    global FRRP_LOG_FILE
    global GENERAL_LOG_FILE
    global MUX
    global PREFIX
    global EXP_ID
    global producer
    global CONST_WAIT_TIME

    mkdir_p('graph_results')
    mkdir_p('general_logs')
    mkdir_p('dr_logs')
    mkdir_p('frrp_logs')

    if len(sys.argv) < 5:
        print('usage: long_path.py <EXP_ID> <ATLAS_AS_FILE> <PREFIX> <WAIT_TIME> <MUX>')
        sys.exit(1)
    producer = KafkaProducer(value_serializer=lambda m: json.dumps(m).encode('ascii'))

    atexit.register(end_collector_call)

    EXP_ID = str(sys.argv[1])
    MUX = str(sys.argv[5])
    PREFIX = str(sys.argv[3])
    CONST_WAIT_TIME = int(sys.argv[4])
    source_as_file = str(sys.argv[2])

    exp_start = arrow.utcnow().isoformat()
    GENERAL_LOG_FILE = "general_logs/general_log_{}_{}_{}.txt".format(EXP_ID, MUX, exp_start)
    DR_LOG_FILE = "dr_logs/default_route_log_{}_{}_{}.txt".format(EXP_ID, MUX, exp_start)
    FRRP_LOG_FILE = "frrp_logs/frrp_log_{}_{}_{}.txt".format(EXP_ID, MUX,  exp_start)

    run_measurements(producer, source_as_file, exp_start)


if __name__ == '__main__':
    main()
