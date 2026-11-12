#!/bin/bash
# tools_src.sh <file under ~/mc3-web> <regex> [context]   grep a source file of the engine tree
#              <file> <from>-<to>                          or print a line range
cd ~/mc3-web || exit 1
if [[ "$2" =~ ^[0-9]+-[0-9]+$ ]]; then sed -n "${2%-*},${2#*-}p" "$1" | cut -c1-200
else grep -n -E -C "${3:-0}" "$2" "$1" | cut -c1-200; fi
