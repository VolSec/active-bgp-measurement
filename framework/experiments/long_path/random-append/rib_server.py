#!/usr/bin/env python
from __future__ import print_function

import argparse

import flask
import rib

app = flask.Flask(__name__)
rib = rib.RIB()

@app.route('/', defaults={'network': None, 'mask': None})
@app.route('/<network>/<int:mask>')
def nlri_get(network, mask):
    prefix = '{}/{}'.format(network, mask) if network else None
    prefixes = rib.get(prefix)
    if prefixes is None:
        prefixes = dict()
    return flask.jsonify(prefixes)

@app.route('/<network>/<int:mask>', methods=['POST', 'PUT'])
def nlri_add(network, mask):
    prefix = '{}/{}'.format(network, mask)
    query = dict()
    for key, val in flask.request.args.items():
        if key in ['as_seq', 'as_set', 'community']:
            val = val.split(',')
            if val == ['']:
                continue
        elif key == 'announce':
            val = boolify(val)
        query[key] = val
    try:
        rib.add(prefix, **query)
    except Exception as e:
        resp = flask.jsonify({'error': str(e)})
        resp.status_code = 400
        return resp
    return nlri_get(network, mask)
    #return aiohttp.web.json_response(self.rib.get(prefix))

@app.route('/<network>/<int:mask>', methods=['DELETE'])
def nlri_del(network, mask):
    prefix = '{}/{}'.format(network, mask)
    rib.remove(prefix)
    return nlri_get(network, mask)

def boolify(val):
    val = val.lower()
    bools = {
        'false': False,
        '0': False,
        'true': True,
        '1': True,
    }
    if val not in bools:
        raise ValueError('Unknown bool value {}'.format(val))
    return bools[val]

def parse_args():
    a = argparse.ArgumentParser()
    a.add_argument('--port', '-p', type=int, default=5000, help='port to listen on')
    return a.parse_args()

def main():
    args = parse_args()
    app.run(port=args.port)

if __name__ == '__main__':
    main()
