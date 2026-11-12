#!/bin/bash
set -e
SR=~/emsdk/upstream/emscripten/cache/sysroot
cp -r ~/ffmpeg-wasm/include/* $SR/include/
cp ~/ffmpeg-wasm/lib/*.a $SR/lib/
mkdir -p $SR/lib/pkgconfig
for f in ~/ffmpeg-wasm/lib/pkgconfig/*.pc; do sed -e "s|^prefix=.*|prefix=$SR|" -e "s|^libdir=.*|libdir=$SR/lib|" -e "s|^includedir=.*|includedir=$SR/include|" "$f" > $SR/lib/pkgconfig/$(basename $f); done
grep -h "^prefix\|^libdir\|^Libs:" $SR/lib/pkgconfig/libavcodec.pc
