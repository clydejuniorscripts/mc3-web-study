#!/bin/bash
# A minimal FFmpeg for the browser build: the Bink demuxer and decoders only
# (LGPL; no GPL parts), static, into ~/ffmpeg-wasm.
set -eo pipefail
source ~/emsdk/emsdk_env.sh >/dev/null 2>&1
cd ~
[ -d ffmpeg-src ] || git clone -q --depth 1 --branch n7.1 https://github.com/FFmpeg/FFmpeg.git ffmpeg-src
cd ffmpeg-src
emconfigure ./configure --prefix="$HOME/ffmpeg-wasm" \
  --target-os=none --arch=x86_32 --enable-cross-compile \
  --cc=emcc --cxx=em++ --ar=emar --ranlib=emranlib --nm=emnm \
  --disable-x86asm --disable-inline-asm --disable-asm --disable-stripping \
  --disable-programs --disable-doc --disable-debug --disable-runtime-cpudetect \
  --disable-autodetect --disable-everything --disable-network --disable-pthreads \
  --disable-swscale --disable-swresample --disable-avdevice --disable-avfilter \
  --enable-decoder=bink,binkaudio_rdft,binkaudio_dct \
  --enable-demuxer=bink --enable-protocol=file \
  --extra-cflags="-O3 -pthread -matomics -mbulk-memory" > ../ffmpeg-configure.log 2>&1 \
  || { tail -30 ../ffmpeg-configure.log; exit 1; }
emmake make -j16 > ../ffmpeg-make.log 2>&1 || { tail -30 ../ffmpeg-make.log; exit 1; }
emmake make install > /dev/null 2>&1
ls -la ~/ffmpeg-wasm/lib
grep -E "^Libs|^Requires" ~/ffmpeg-wasm/lib/pkgconfig/libavformat.pc
echo FFMPEG_OK
