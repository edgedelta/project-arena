#!/bin/sh
i=0
while true; do
  i=$((i+1))
  echo "ERROR upstream gateway timeout after 30000ms (attempt $i) code=504"
  sleep 0.1
done
