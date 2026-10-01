#!/bin/sh
# Reads its endpoint from the environment, then idles.
echo "config loader starting"
echo "endpoint: ${ENDPOINT_URL:-unset}"
sleep infinity
