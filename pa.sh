#!/bin/bash
# vi: ts=2 sw=2 et

die() {
  printf '%s\n' "$1"
  exit 1
}

PATH=./node_modules/.bin/:$PATH

set -eu
type node || source "$NVM_DIR/nvm.sh"
type pip || source ./venv/bin/activate
type osmtogeojson || die 'please npm install osmtogeojson'
type aws || die 'please pip install awscli'
type curl tippecanoe jq
set -x

query='[out:json];

(
  area[wikidata=Q1400]->.a;  // Pennsylvania
  ( rel(area.a)[type=boundary][boundary=administrative];
    rel(area.a)[type=boundary][boundary=census]; );

  area[wikidata=Q1384]->.a;  // New York
  ( rel(area.a)[type=boundary][boundary=administrative];
    rel(area.a)[type=boundary][boundary=census]; );

  area[wikidata=Q1397]->.a;  // Ohio
  ( rel(area.a)[type=boundary][boundary=administrative];
    rel(area.a)[type=boundary][boundary=census]; );
);

out;>;out skel qt;'

if [[ marker -nt out.json ]]; then
  curl https://overpass-api.de/api/interpreter -G --data-urlencode $"data=$query" > out.json
fi

if [[ out.json -nt geom.json ]]; then
  osmtogeojson out.json > geom.json
fi

if [[ geom.json -nt geom.mbtiles ]]; then
  rm -f geom.mbtiles
  tippecanoe -o geom.mbtiles geom.json
fi

MAPBOX_ACCESS_TOKEN=$(<~/tokens.json jq -r .mapbox_secret)
curl -X POST "https://api.mapbox.com/uploads/v1/jleedev/credentials?access_token=$MAPBOX_ACCESS_TOKEN" > s3.json

export AWS_ACCESS_KEY_ID=$(<s3.json jq -r .accessKeyId)
export AWS_SECRET_ACCESS_KEY=$(<s3.json jq -r .secretAccessKey)
export AWS_SESSION_TOKEN=$(<s3.json jq -r .sessionToken)
export BUCKET=$(<s3.json jq -r .bucket)
export KEY=$(<s3.json jq -r .key)
export AWS_DEFAULT_REGION=us-east-1

# env | sort 

aws s3 cp geom.mbtiles s3://${BUCKET}/${KEY}

jq -s add <(<s3.json jq {url}) <(printf '{"tileset":"jleedev.pa-admin"}') > upload.json

curl -X POST --header "Content-Type:application/json" "https://api.mapbox.com/uploads/v1/jleedev?access_token=$MAPBOX_ACCESS_TOKEN" --data @upload.json > upload-result.json

# nb. contains quotes
UPLOAD_ID=$(<upload-result.json jq .id)

COMPLETE=false
while [[ "$COMPLETE" != true ]]
do
  sleep 15
  curl -s "https://api.mapbox.com/uploads/v1/jleedev?access_token=$MAPBOX_ACCESS_TOKEN" > progress.json
  COMPLETE=$(<progress.json jq "map(select(.id==$UPLOAD_ID))[0].complete")
done
