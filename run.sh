#!/bin/bash

cd "$(dirname $0)"
export NVM_DIR=/home/josh/.nvm

echo begin $0
date

. $NVM_DIR/nvm.sh

. ./venv/bin/activate
./loader.py

echo end $0
date
