#!/bin/bash

echo "Starting collectors for all PEERING prefixes on /25's..."
python start_one_off_collector.py 184-164-224-0-25mask-peering 184.164.224.0/25 &
python start_one_off_collector.py 184-164-225-0-25mask-peering 184.164.225.0/25 &
python start_one_off_collector.py 184-164-228-0-25mask-peering 184.164.228.0/25 &
python start_one_off_collector.py 184-164-229-0-25mask-peering 184.164.229.0/25
