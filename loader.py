#!/usr/bin/env python3

import boto3
from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
import requests
import subprocess
import sys
import time

logging.Formatter.default_msec_format = "%s.%03d"
logging.basicConfig(
    level="INFO", format="%(asctime)s:%(levelname)s:%(name)s:%(message)s"
)
log = logging.getLogger()


def overpass(state_wikidata):
    return f"""
    [out:json];
    area[wikidata="{state_wikidata}"]->.a;
    ( rel(area.a)[type=boundary][boundary=administrative];
      rel(area.a)[type=boundary][boundary=census]; );
    out;>;out skel qt;
    """


states = [
    ("pa", "Q1400"),
    ("ny", "Q1384"),
    ("oh", "Q1397"),
    ("mi", "Q1166"),
    ("ma", "Q771"),
]

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

MAPBOX_ACCESS_TOKEN = json.loads(Path("~/tokens.json").expanduser().read_bytes())[
    "mapbox_secret"
]
MAPBOX_USERNAME = "jleedev"


def osmtogeojson(x):
    cmd = subprocess.run(
        ["./node_modules/.bin/osmtogeojson"],
        input=x,
        check=True,
        stdout=subprocess.PIPE,
    )
    return cmd.stdout


def tippecanoe(src, dst):
    subprocess.check_call(["tippecanoe", "--force", "-o", dst, src])


def fresh(p):
    # True = p is a file and was modified less than 1 day ago
    p = Path(p)
    if not p.is_file():
        return False
    stat = p.stat()
    mtime = datetime.utcfromtimestamp(stat.st_mtime)
    diff = datetime.now() - mtime
    return diff < timedelta(days=1)


def process_state(state, wikidata):
    log.info("processing %s", state)
    Path("./data").mkdir(exist_ok=True)
    osm_path = f"./data/{state}.json"
    geojson_path = f"./data/{state}.geojson"
    mbtiles_path = f"./data/{state}.mbtiles"
    if not fresh(osm_path):
        log.info("calling overpass for %s", state)
        overpass_query = overpass(wikidata)
        log.info("overpass query is %s", overpass_query)
        r = requests.post(OVERPASS_URL, data={"data": overpass_query})
        r.raise_for_status()
        log.info("saving osm output")
        Path(osm_path).write_bytes(r.content)
    if not fresh(geojson_path):
        log.info("converting to geojson")
        osm = Path(osm_path).read_bytes()
        geojson = osmtogeojson(osm)
        log.info("saving geojson output")
        Path(geojson_path).write_bytes(geojson)
    if not fresh(mbtiles_path):
        log.info("calling tippecanoe")
        tippecanoe(geojson_path, mbtiles_path)
        log.info("tiles produced")
    return mbtiles_path


MAPBOX_UPLOAD_CREDENTIAL_URL = (
    f"https://api.mapbox.com/uploads/v1/{MAPBOX_USERNAME}/credentials"
)
MAPBOX_UPLOAD_URL = f"https://api.mapbox.com/uploads/v1/{MAPBOX_USERNAME}"


def upload(state, mbtiles_path):
    log.info("starting upload of %s", state)
    r = requests.post(
        MAPBOX_UPLOAD_CREDENTIAL_URL, params={"access_token": MAPBOX_ACCESS_TOKEN}
    )
    r.raise_for_status()
    cred = r.json()
    log.info("sending to s3")
    s3 = boto3.client(
        "s3",
        aws_access_key_id=cred["accessKeyId"],
        aws_secret_access_key=cred["secretAccessKey"],
        aws_session_token=cred["sessionToken"],
        region_name="us-east-1",
    )
    s3.put_object(Body=open(mbtiles_path, "rb"), Bucket=cred["bucket"], Key=cred["key"])
    log.info("finalizing upload")
    r = requests.post(
        MAPBOX_UPLOAD_URL,
        params={"access_token": MAPBOX_ACCESS_TOKEN},
        json={"url": cred["url"], "tileset": f"{MAPBOX_USERNAME}.{state}-admin"},
    )
    r.raise_for_status()
    upload_id = r.json()["id"]
    return upload_id


def poll_progress(upload_id):
    log.info("waiting for upload to process")
    r = requests.get(MAPBOX_UPLOAD_URL, params={"access_token": MAPBOX_ACCESS_TOKEN})
    r.raise_for_status()
    for o in r.json():
        if o["id"] == upload_id:
            return o["complete"]
    raise IndexError(upload_id)


def run(arg):
    log.info("starting up for %s", arg)
    for (state, wikidata) in arg:
        mbtiles_path = process_state(state, wikidata)
        upload_id = upload(state, mbtiles_path)
        while not poll_progress(upload_id):
            time.sleep(15)
    log.info("done")


if __name__ == "__main__":
    arg = sys.argv[1:]
    if arg:
        d = dict(states)
        run([(state, d[state]) for state in arg])
    else:
        run(states)
