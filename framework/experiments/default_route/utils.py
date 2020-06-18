import requests


def prefer_stability(data):
    if data['count'] > 1:
        for entry in data['results']:
            for tag in entry['tags']:
                if 'IPv4 Stable 30d' in tag.values():
                    return entry['id']
        return data['results'][0]['id']
    elif data['count'] == 1:
        return data['results'][0]['id']
    else:
        return ''


def find_nodes_by_asn(asn):
    response = requests.get('https://atlas.ripe.net:443/api/v2/probes/?asn='+asn).json()
    probe = prefer_stability(response)
    return probe


def asn_has_probe(asn):
    response = requests.get('https://atlas.ripe.net:443/api/v2/probes/?asn='+str(asn)).json()
    if response['count'] > 0:
        return True
    else:
        return False