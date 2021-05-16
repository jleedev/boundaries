#!/usr/bin/env python3

import boto3
import requests

from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
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


def run(arg):
    log.info("starting up for %s", arg)
    for (state, wikidata) in arg:
        mbtiles_path = process_state(state, wikidata)
    log.info("produced %s", mbtiles_path)


if __name__ == "__main__":
    arg = sys.argv[1:]
    if arg:
        d = dict(states)
        run([(state, d[state]) for state in arg])
    else:
        run(states)
