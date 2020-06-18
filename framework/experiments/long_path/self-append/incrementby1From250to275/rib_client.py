#!/usr/bin/env python
from __future__ import print_function

import logging
logging.basicConfig(level=logging.DEBUG)

import json
import requests
import time

import rib

class NLRIClient(rib.NLRI):
    def __init__(self, *args, **kwargs):
        host = kwargs.get('host', '127.0.0.1')
        port = kwargs.get('port', 5000)
        for kwarg in ['host', 'port']:
            if kwarg in kwargs: del kwargs[kwarg]
        self.uri = 'http://{}:{}'.format(host, port)
        super(NLRIClient, self).__init__(*args, **kwargs)

    def _request(self, method):
        params = {
            'next_hop': str(self.next_hop),
            'as_seq': ','.join(map(str, self.as_seq)),
            'as_set': ','.join(map(str, self.as_set)),
            'community': ','.join(self.community),
            'announce': str(self.announce),
        }

        return requests.request(method, '{}/{}'.format(self.uri, self.prefix), params=params)

    def _get(self):
        return self._request('GET')

    def _post(self):
        return self._request('POST')

    def _delete(self):
        return self._request('DELETE')

    def _do_announce(self):
        if self._announce:
            self._post()

    def _do_withdraw(self):
        if not self._announce:
            self._post()

    def __del__(self):
        self._delete()

if __name__ == '__main__':
    try:
        x = NLRIClient('208.45.212.0/25', port=5000)
        for y in range(500):
            x.as_seq.append('3450')
            time.sleep(.1)
            print(x)
    except (KeyboardInterrupt, SystemExit):
        pass
