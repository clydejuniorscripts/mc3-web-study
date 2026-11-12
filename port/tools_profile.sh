#!/bin/bash
# usage: tools_profile.sh reset | show | save | files
case "$1" in
  reset) curl -s "http://127.0.0.1:8099/dev/profile?reset=1"; echo ;;
  save)  curl -s "http://127.0.0.1:8099/dev/profile?save=1"; echo
         cp ~/mc3-web/web/boot-profile.json /mnt/c/Games/mc3-web-port/web/boot-profile.json ;;
  files) curl -s "http://127.0.0.1:8099/dev/profile?list=1" | python3 -c "
import json,sys,collections
p=json.load(sys.stdin); c=collections.Counter(x[0] for x in p['chunks'])
print(p['pieces'],'pieces',round(p['bytes']/1e6,1),'MB')
for k,v in c.most_common(14): print('%5d  %s'%(v,k))" ;;
  *)     curl -s "http://127.0.0.1:8099/dev/profile"; echo ;;
esac
