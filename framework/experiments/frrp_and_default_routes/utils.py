import requests
from csv import reader

MUX_DATA = None


class MuxPeer:
    def __init__(self, name, mux_name, asn, sess_id, ip_version, is_transit=False, is_route_server=False):
        self.name = name
        self.mux_name = mux_name
        self.asn = asn
        self.sess_id = sess_id
        self.ip_version = ip_version
        self.is_transit = is_transit
        self.is_route_server = is_route_server


class Mux:
    def __init__(self, name, port, ip_v4, ip_v6, origin=47065):
        self.name = name
        self.port = port
        self.ip_v4 = ip_v4
        self.ip_v6 = ip_v6
        self.origin = origin
        self.peers = []
        self.transits = []

    def add_peer(self, peer, is_transit=False):
        if is_transit:
            self.transits.append(peer)
        else:
            self.peers.append(peer)

    def build_communities(self, ip_version, complete=True):
        filtered_transits = [t for t in self.transits if t.ip_version == ip_version]
        filtered_peers = [p for p in self.peers if p.ip_version == ip_version]

        if complete:
            community_list = []
            for t in filtered_transits:
                community_list.append('{}:{}'.format(str(self.origin), str(t.sess_id)))
            for p in filtered_peers:
                community_list.append('{}:{}'.format(str(self.origin), str(p.sess_id)))
            return community_list
        else:
            community_list = []
            for t in filtered_transits:
                community_list.append('{}:{}'.format(str(self.origin), str(t.sess_id)))
            return community_list


def prefer_stability(data):
    if data['count'] > 0:
        probes = set()
        for entry in data['results']:
            for tag in entry['tags']:
                if entry["status"]["name"] == "Connected":
                    probes.add(entry['id'])
        return probes
    else:
        return None


def find_probes_by_asn(asn):
    response = requests.get('https://atlas.ripe.net:443/api/v2/probes/?asn='+str(asn)).json()
    probes = prefer_stability(response)
    return probes


def asn_has_probe(asn):
    response = requests.get('https://atlas.ripe.net:443/api/v2/probes/?asn='+str(asn)).json()
    if response['count'] > 0:
        print(response)
        return True
    else:
        return False

def setup_mux_data():
    global MUX_DATA

    MUX_DATA = dict()

    with open('port_to_mux.csv', 'r') as f:
        for i, line in enumerate(f.readlines()):
            if i != 0:
                line = line.rstrip()
                line = line.split(',')

                mux_name = str(line[0])
                port = int(line[1])
                ip_v4 = str(line[2])
                ip_v6 = str(line[3])

                mux = Mux(mux_name, port, ip_v4, ip_v6)
                MUX_DATA[mux_name] = mux

    with open('peering-report-bgppeertable.csv', 'r') as f:
        csv_reader = reader(f)
        for i, line in enumerate(csv_reader):
            if i != 0:
                peer_name = str(line[1])
                peer_mux_name = str(line[0])
                peer_asn = int(line[2])
                peer_sess_id = int(line[8])
                peer_ip_version = str(line[4])

                if str(line[6]) == "✔":
                    peer_is_transit = True
                else:
                    peer_is_transit = False

                if str(line[7]) == "✔":
                    peer_is_route_server = True
                else:
                    peer_is_route_server = False

                peer = MuxPeer(peer_name, peer_mux_name, peer_asn, peer_sess_id, peer_ip_version.lower(),
                    is_transit=peer_is_transit, is_route_server=peer_is_route_server)

                MUX_DATA[peer_mux_name].add_peer(peer, is_transit=peer_is_transit)


def get_mux_data(name, ip_version='ipv4', with_peers=True):
    global MUX_DATA

    mux = MUX_DATA[name]
    port = mux.port

    if with_peers:
        community_list = mux.build_communities(ip_version)
        return port, community_list
    else:
        community_list = mux.build_communities(ip_version, complete=False)
        return port, community_list


def get_mux_for_port(port):
    global MUX_DATA

    for name, mux in MUX_DATA.items():
        if mux.port == int(port):
            return name
    else:
        raise ValueError('Mux does not exist for port {}!'.format(str(port)))

def get_mux_transits(port):
    global MUX_DATA

    for name, mux in MUX_DATA.items():
        if mux.port == port:
            asns = []
            for t in mux.transits:
                asns.append(t.asn)
            return asns
