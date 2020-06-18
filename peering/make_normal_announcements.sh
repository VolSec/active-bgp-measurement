#!/bin/bash

echo "Announcing to PEERING..."
sudo ./peering prefix announce "184.164.224.0/24"
sudo ./peering prefix announce "184.164.225.0/24"
sudo ./peering prefix announce "184.164.228.0/24"
sudo ./peering prefix announce "184.164.229.0/24"
echo "All announcements made."
