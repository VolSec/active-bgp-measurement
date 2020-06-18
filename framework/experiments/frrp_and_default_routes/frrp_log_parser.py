#!/usr/bin/env python

import re


class AnnotatedASPath:
    def __init__(self):
        self.ases = []
        self.rtts = []
        self.length = 0
        self.atlas_m_id = None
        self.poisons = None

    def iter_path(self):
        for _as, _rtt in zip(self.ases, self.rtts):
            yield _as, _rtt

    def add_as(self, _as, rtt):
        self.ases.append(_as)
        self.rtts.append(rtt)
        self.length += 1

    def __equal__(self, other):
        if self.ases == other.ases:
            return True
        else:
            return False

    def __repr__(self):
        return "ASPath of length ({}) with Poisons ({}): {}".format(self.length, ",".join([str(x) for x in self.poisons]),
                                                     ",".join(["{}:{}".format(x1, x2) for x1, x2 in zip(self.ases, self.rtts)]))


class FRRPRun:
    def __init__(self, src_asn):
        self.src_asn = src_asn
        self.errors = []
        self.final_graph_path = None
        self.no_stable_probe = False
        self.has_default_route = False
        self.graph_path = None
        self.poison_cache = None

        self.original_path = None
        self.discovered_paths = []

        self.lost_connectivity_paths = []

        self.initial_lost_connectivity_failure = False

    def is_unique_path(self, path):
        if path == self.original_path or path in self.discovered_paths:
            return False
        else:
            return True

    def add_discovered_path(self, path):
        if self.is_unique_path(path):
            self.discovered_paths.append(path)
        else:
            print("Non-unique path: {}".format(path))

    def add_lost_connectivity_path(self, path):
        self.lost_connectivity_paths.append(path)

    def add_error(self, error):
        self.errors.append(error)


def parse_valid_entry(frrp_run, result, lost_connectivity_entry=False):
    original_path = False
    annotated_as_path = AnnotatedASPath()
    raw_as_path = result[7]
    raw_rtt_path = result[9]
    raw_poisons = result[5]
    m_id = int(result[3])

    if raw_poisons is None and raw_as_path is not None:
        original_path = True
        poisons = []
    else:
        poisons = [int(x) for x in raw_poisons]

    as_rtts = [x.split('-') for x in raw_rtt_path]
    annotated_as_path.poisons = poisons
    annotated_as_path.atlas_m_id = m_id

    for _as, _rtt in as_rtts:
        annotated_as_path.add_as(int(_as), float(_rtt))

    if lost_connectivity_entry:
        frrp_run.add_lost_connectivity_path(annotated_as_path)
    else:
        if original_path:
            frrp_run.original_path = annotated_as_path
        else:
            frrp_run.add_discovered_path(annotated_as_path)


def parse_file(filename):
    as_path_pattern = re.compile(r"\[(.*)\]")
    frrp_runs = dict()

    with open(filename, 'r') as f:
        for line in f.readlines():
            line = line.rstrip()
            if line.startswith('#'):
                continue

            split_line = line.split('|')
            result_type, result = split_line[0], split_line[1]
            r = re.compile(r'(?:\[(?P<nested>.*?)\]|(?P<flat>[^,]+?)),')
            result = []
            for match in r.finditer(line + ","):
                if match.group('nested'): # It's a sub-array
                    result.append(match.group('nested').split(","))
                else: # It's a normal top-level element
                    result.append(match.group('flat'))

            src_asn = int(result[1])
            frrp_run = frrp_runs.get(src_asn, None)
            preexisting = True
            if frrp_run is None:
                frrp_run = FRRPRun(src_asn)
                frrp_runs[src_asn] = frrp_run
                preexisting = False

            if int(result_type) == -1:
                if frrp_run.initial_lost_connectivity_failure:
                    frrp_run.add_error(str(result[3]))
                    continue
            elif int(result_type) == 1:
                if frrp_run.initial_lost_connectivity_failure:
                    continue
                frrp_run.final_graph_path = str(result[3])
            elif int(result_type) == 2:
                if not preexisting:
                    frrp_run.initial_lost_connectivity_failure = True
                    print(line)
                else:
                    parse_valid_entry(frrp_run, result, lost_connectivity_entry=True)
            elif int(result_type) == 0:
                parse_valid_entry(frrp_run, result)

    return frrp_runs
