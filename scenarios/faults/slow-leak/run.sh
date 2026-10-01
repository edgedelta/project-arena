#!/bin/sh
CACHE_DIR=${CACHE_DIR:-/cache}
i=0
while true; do
  i=$((i+1))
  dd if=/dev/zero of="$CACHE_DIR/data" bs=1048576 count=1 seek=$i 2>/dev/null
  echo "WARN cache grew to ${i}MiB, request latency degrading"
  if [ $((i % 2)) -eq 0 ]; then
    echo "ERROR request timed out after 5000ms (upstream slow to respond)"
  fi
  sleep 60
done
