#!/bin/bash

version=$1
mkdir empty_dir
rm -f ./versions/version_manifest.json
rsync -a --delete empty_dir/ ./src/$version
rsync -a --delete empty_dir/ ./versions/$version
rsync -a --delete empty_dir/ ./mappings/$version
rmdir empty_dir

sleep 1
python.exe ./main.py client $version &
pid1=$!
sleep 1
python.exe ./main.py server $version &
pid2=$!
sleep 1

wait $pid1 $pid2