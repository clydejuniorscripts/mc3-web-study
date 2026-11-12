#!/bin/bash
# Pin the engine players get.  tools_pin.sh good  -> the build kept before the last rebuild
#                              tools_pin.sh new   -> release work-dub/build-web (after testing it)
cd ~/mc3-web/work-dub || exit 1
mkdir -p build-web-live
case "$1" in
  good) cp -p build-web-good/mcdub3.js build-web-good/mcdub3.wasm build-web-live/ ;;
  new)  cp -p build-web/mcdub3.js build-web/mcdub3.wasm build-web-live/ ;;
  *)    echo "usage: tools_pin.sh good|new"; exit 1 ;;
esac
ls -la --time-style=long-iso build-web-live/ build-web/mcdub3.wasm build-web-good/mcdub3.wasm | cut -c24-
