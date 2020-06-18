import datetime
import time

from ripe.atlas.cousteau import AtlasResultsRequest
from ripe.atlas.cousteau import (
  Ping,
  Traceroute,
  AtlasSource,
  AtlasCreateRequest
)


ATLAS_API_KEY = "REPLACE"

def submit_traceroute(asn):
    traceroute_time = int(time.time())

    traceroute = Traceroute(
        af=4,
        target="208.45.214.0",
        description="{}_{}".format(asn, traceroute_time),
        protocol="ICMP",
    )

    source = AtlasSource(type="asn", value=asn, requested=1)

    atlas_request = AtlasCreateRequest(
        start_time=datetime.datetime.utcnow(),
        key=ATLAS_API_KEY,
        measurements=[traceroute],
        sources=[source],
        is_oneoff=True
    )

    (is_success, response) = atlas_request.create()
    if not is_success:
        return None, traceroute_time

    measurement_id = response["measurements"][0]

    print("Measurement ID of {} for ongoing traceroute".format(measurement_id))

    return measurement_id, traceroute_time


def wait_on_measurement(measurement_id):
    measurement_result = None
    err = False

    kwargs = {
        "msm_id": int(measurement_id)
    }

    # Wait to get a result
    while True:
        time.sleep(10)
        print("Checking measurement status...")
        is_success, results = AtlasResultsRequest(**kwargs).create()
        if is_success and len(results) != 0:
            print(results)
            break


def main():
    measurement_id, _ = submit_traceroute(4)
    wait_on_measurement(measurement_id)


if __name__ == '__main__':
    main()
