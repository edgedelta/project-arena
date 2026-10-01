#!/bin/sh
# cache-warmer <fill|refresh>
#   fill     one-shot: warm the cache to FILL_TARGET_BYTES, then apply CACHE_MAXMEMORY
#   refresh  long-running: keep writing small entries, report rejected writes
REDIS_ADDR=${REDIS_ADDR:-redis}
REDIS_PORT=${REDIS_PORT:-6379}
KEY_PREFIX=${KEY_PREFIX:-warm}
rc() { redis-cli -h "$REDIS_ADDR" -p "$REDIS_PORT" "$@"; }

fill() {
  FILL_TARGET_BYTES=${FILL_TARGET_BYTES:-251658240}
  PAYLOAD_BYTES=${PAYLOAD_BYTES:-65536}
  echo "warming cache: target $FILL_TARGET_BYTES bytes, no TTL"
  i=0
  while true; do
    used=$(rc info memory | tr -d '\r' | awk -F: '/^used_memory:/{print $2}')
    [ -z "$used" ] && { echo "cannot read used_memory, retrying"; sleep 2; continue; }
    [ "$used" -ge "$FILL_TARGET_BYTES" ] && break
    payload=$(head -c "$PAYLOAD_BYTES" /dev/urandom | base64 | tr -d '\n')
    j=0
    while [ $j -lt 50 ]; do
      j=$((j+1)); i=$((i+1))
      rc SET "$KEY_PREFIX:$i" "$payload" >/dev/null 2>&1
    done
    echo "warmed $i keys, used_memory=$used"
  done
  echo "warm-up complete: $i keys, used_memory=$used"
  if [ -n "$CACHE_MAXMEMORY" ]; then
    echo "applying memory policy: maxmemory=$CACHE_MAXMEMORY"
    rc CONFIG SET maxmemory "$CACHE_MAXMEMORY"
    echo "memory policy applied"
  fi
}

refresh() {
  PAYLOAD_BYTES=${PAYLOAD_BYTES:-4096}
  echo "cache warmer starting against $REDIS_ADDR:$REDIS_PORT"
  i=0
  while true; do
    i=$((i+1))
    payload=$(head -c "$PAYLOAD_BYTES" /dev/urandom | base64 | tr -d '\n')
    out=$(rc SET "$KEY_PREFIX:w:$i" "$payload" 2>&1)
    case "$out" in
      OK) sleep 1 ;;
      *OOM*) echo "write rejected (OOM) at key $i: $out"; sleep 5 ;;
      *) echo "write error at key $i: $out"; sleep 2 ;;
    esac
  done
}

case "${1:-}" in
  fill) fill ;;
  refresh) refresh ;;
  *) echo "usage: cache-warmer <fill|refresh>" >&2; exit 2 ;;
esac
