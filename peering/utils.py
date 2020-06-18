import requests


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
