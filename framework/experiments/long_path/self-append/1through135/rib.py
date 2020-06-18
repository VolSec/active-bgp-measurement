#!/usr/bin/env python
from __future__ import print_function

import sys
import json
import ipaddress

from functools import wraps

if sys.version_info >= (3, 0, 0):
    from collections import UserList, MutableSet
else:
    from UserList import UserList
    from collections import MutableSet


def callback_after(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        f(*args, **kwargs)
        args[0]._callback()
    return wrapper


class BGPList(UserList):
    def __init__(self, *args, **kwargs):
        self._callback = kwargs.pop('change_callback', lambda: 0)
        if len(args) > 0:
            for idx, item in enumerate(args[0]):
                args[0][idx] = self._check(item)
        super(BGPList, self).__init__(*args, **kwargs)
        #UserList.__init__(self, args[0])

    def _check(self, value):
        return value

    @callback_after
    def __setitem__(self, item, value):
        value = self._check(value)
        super(BGPList, self).__setitem__(item, value)

    @callback_after
    def append(self, value):
        value = self._check(value)
        super(BGPList, self).append(value)

    @callback_after
    def insert(self, index, value):
        value = self._check(value)
        super(BGPList, self).insert(index, value)

    @callback_after
    def pop(self, i=-1):
        super(BGPList, self).pop(i)

    @callback_after
    def remove(self, value):
        super(BGPList, self).remove(value)

    @callback_after
    def prepend(self, value):
        self.insert(0, value)


class ASList(BGPList):
    def _check(self, value):
        """Performs check on value to ensure it is a valid asn

        :param value: ASN to check
        :type value: str or int
        :returns: int ASN
        :raises: ValueError on invalid ASN"""
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ValueError('ASN could not be converted to int: ({})'.format(value))
        if value < 0 or value >= 2**32:
            raise ValueError('ASN out of range: ({})'.format(value))
        return value


class CommunityList(BGPList):
    """Keeps track of a set of communities.

    Communities can be added in the following formats:

        int
        two colon-separated shorts in str
        int as str
        hex int as str
    """
    def _check(self, value):
        """Performs check on value to ensure it is a valid community attribute

        :param value: attribute to check
        :type value: str or int
        :returns: str representation of community
        :raises: ValueError on invalid community"""
        if isinstance(value, str):
            if ':' in value:
                parts = value.split(':')
                if len(parts) != 2:
                    raise ValueError('Too many colons in community: ({})'.format(value))
                for part in parts:
                    try:
                        part = int(part)
                        if part < 0 or part >= 2**16:
                            raise ValueError('Community part out of range: ({}) ({})'.format(part, value))
                    except TypeError:
                        raise ValueError('Community part could not be converted to int: ({}) ({})'.format(part, value))
            else:
                if value.startswith('0x'):
                    try:
                        value = int(value)
                    except TypeError:
                        raise ValueError('Community value is invalid hex: ({})'.format(value))
                else:
                    try:
                        value = int(value)
                    except TypeError:
                        raise ValueError('Community value is invalid integer: ({})'.format(value))

        elif isinstance(value, int):
            if value < 0 or value >= 2**32:
                raise ValueError('Community value out of range: ({})'.format(value))
            lpart = value >> 16
            rpart = value & 0xffff
            value = '{}:{}'.format(lpart, rpart)

        return value


class NLRI(object):
    """Data structure for Network Layer Reachability Information

    If self.announce is True, any variable change will cause an UPDATE to be sent
    A change of self.announce from True to False will cause a withdraw
    """
    def __init__(self, prefix, next_hop='self', community=[], as_seq=[], as_set=[], announce=True):
        """Constructor for NLRI

        :param prefix: CIDR prefix
        :type prefix: str
        :param next_hop: IP address of next-hop or 'self'
        :type next_hop: str
        :param community: List of community values
        :type community: list
        :param as_seq: AS sequence list
        :type as_seq: list
        :param as_set: AS set list
        :type as_set: set
        :param announce: Boolean which controls if NLRI is announced
        :type announce: bool
        :returns: NLRI object
        """
        self._announce = False
        self._callback = self._do_announce
        self._next_hop = 'self'
        self._community = CommunityList(community, change_callback=self._callback)
        self._as_seq = ASList(as_seq, change_callback=self._callback)
        self._as_set = ASList(as_set, change_callback=self._callback)
        self._prefix = ipaddress.ip_network(prefix, strict=False)
        self.next_hop = next_hop
        self.announce = announce

    def __eq__(self, other):
        return self.prefix == other.prefix

    def __hash__(self):
        return hash(self.prefix)

    @property
    def as_seq(self):
        return self._as_seq

    @as_seq.setter
    @callback_after
    def as_seq(self, value):
        self._as_seq = ASList(value, change_callback=self._callback)

    @property
    def as_set(self):
        return self._as_set

    @as_set.setter
    @callback_after
    def as_set(self, value):
        self._as_set = ASList(value, change_callback=self._callback)

    @property
    def community(self):
        return self._community

    @community.setter
    @callback_after
    def community(self, value):
        self._community = CommunityList(value, change_callback=self._callback)

    @property
    def network(self):
        return str(self.prefix.network_address)

    @property
    def masklen(self):
        return self.prefix.prefixlen

    @property
    def announce(self):
        return self._announce

    @announce.setter
    def announce(self, value):
        if not isinstance(value, bool): 
            value = bool(value)
            #raise ValueError("announce must be bool")
        if self._announce != value:
            self._announce = value
            if value == False:
                self._do_withdraw()
            else:
                self._do_announce()

    @property
    def next_hop(self):
        return self._next_hop

    @next_hop.setter
    def next_hop(self, value):
        if value == 'self':
            if self._next_hop != value:
                self._next_hop = 'self'
                self._callback()
        else:
            addr = ipaddress.ip_address(value)
            if self._next_hop != addr:
                self._next_hop = addr
                self._callback()

    @property
    def prefix(self):
        return self._prefix

    @prefix.setter
    def prefix(self, prefix):
        new_prefix = ipaddress.ip_network(prefix, strict=False)
        if self._prefix and new_prefix == self._prefix:
            return
        if self.announce:
            # Must do a withdraw of the old prefix
            self.announce = False
            self._prefix = new_prefix
            self.announce = True
        else:
            self._prefix = new_prefix

    @property
    def path(self):
        path = list(map(int, self.as_seq))
        if len(self.as_set) > 0:
            path.append(list(map(int, self.as_set)))
        return path

    def _do_announce(self):
        if self.announce:
            fprint('announce ' + str(self))

    def _do_withdraw(self):
        if not self.announce:
            fprint('withdraw ' + str(self))

    def __del__(self):
        self.announce = False

    def __str__(self):
        s = ['route {} next-hop {}'.format(self.prefix, self.next_hop)]
        if self.community:
            s.append('community [ {} ]'.format(' '.join(self.community)))
        if self.path:
            s.append('as-path {}'.format(self.path).replace(',', ''))
            #s.append('as-path [ {} ]'.format(' '.join(self.path)))
        return ' '.join(s)

    def __repr__(self):
        return 'NLRI({})'.format(self.prefix)

    def to_dict(self):
        return {
            'prefix': str(self.prefix),
            'next_hop': str(self.next_hop),
            'as_seq': list(self.as_seq),
            'as_set': list(self.as_set),
            'community': list(self.community),
            'announce': self.announce,
        }

    @staticmethod
    def from_dict(d):
        prefix = d['prefix']
        del d['prefix']
        return NLRI(prefix, **d)


class RIB(object):
    """Manages a unique collection of NLRI objects"""
    def __init__(self):
        self.nlri = dict()

    def __contains__(self, prefix):
        return prefix is not None and len(self.get(prefix)) > 0

    def get(self, prefix=None):
        """Returns a prefix or all prefixes in dict form
        :param prefix: Prefix to read.  None for all prefixes.
        :type prefix: str / ipaddress.IPNetwork or NoneType
        """
        if prefix is None:
            return {str(x): self.nlri[x].to_dict() for x in self.nlri}
        if isinstance(prefix, str):
            try:
                prefix = ipaddress.ip_network(prefix, strict=False)
            except ValueError:
                return None
        if prefix in self.nlri:
            return {str(prefix): self.nlri[prefix].to_dict()}
        return dict()

    def add(self, prefix, **kwargs):
        """Creates or updates a prefix
        :param prefix: Prefix to create/update
        :type prefix: str or ipaddress.IPNetwork
        :param kwargs: See NLRI args
        """
        if isinstance(prefix, str):
            prefix = ipaddress.ip_network(prefix, strict=False)
        if prefix in self.nlri:
            #raise ValueError('Prefix {!r} already exists in table'.format(prefix))
            for kwarg in kwargs:
                #self.nlri[prefix].__dict__[kwarg] = kwargs[kwarg]
                setattr(self.nlri[prefix], kwarg, kwargs[kwarg])
        else:
            nlri = NLRI(prefix, **kwargs)
            self.nlri[nlri.prefix] = nlri

    def remove(self, prefix):
        """Deletes a prefix and withdraws if it is announced
        :param prefix: Prefix to delete
        :type prefix: str or ipaddress.IPNetwork
        """
        if isinstance(prefix, str):
            prefix = ipaddress.ip_network(prefix, strict=False)
        if prefix in self.nlri:
            self.nlri[prefix].announce = False
            del self.nlri[prefix]


def fprint(data, file=sys.stdout, end='\n'):
    """Mimics basic print() functionality but flushes file to cause ExaBGP to read it instantly"""
    file.write('{}{}'.format(data, end))
    file.flush()
