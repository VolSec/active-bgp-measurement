#!/usr/bin/env python


from bgp_collector import BGPCollector
import logging
#logging.basicConfig(level=logging.DEBUG)


def main():
    collector = BGPCollector()
    collector.start()


if __name__ == '__main__':
    main()
