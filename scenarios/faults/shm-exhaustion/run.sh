#!/bin/sh
# Stages a scratch buffer in shared memory before transcoding. A container
# runtime provides only 64 MiB of /dev/shm unless told otherwise; this
# workload needs SCRATCH_MIB.
SCRATCH_MIB=${SCRATCH_MIB:-128}
echo "media worker starting: staging ${SCRATCH_MIB}MiB scratch"
df -h /dev/shm
if ! dd if=/dev/zero of=/dev/shm/scratch bs=1M count="$SCRATCH_MIB" 2>/dev/null; then
  echo "scratch write failed: $(df -h /dev/shm | tail -1)"
  exit 1
fi
echo "scratch staged"
sleep infinity
