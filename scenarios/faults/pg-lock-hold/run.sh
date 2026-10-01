#!/bin/sh
# Migration step 1 of 3: take an exclusive lock on the target table and hold it
# for the duration of the maintenance window.
TARGET_TABLE=${TARGET_TABLE:-catalog.products}
HOLD_SECONDS=${HOLD_SECONDS:-86400}
echo "catalog maintenance: preparing schema change on $TARGET_TABLE"
until psql -tAc 'select 1' >/dev/null 2>&1; do echo "waiting for database"; sleep 2; done
echo "acquiring exclusive lock on $TARGET_TABLE (migration step 1 of 3)"
psql -v ON_ERROR_STOP=1 -c "BEGIN; LOCK TABLE $TARGET_TABLE IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep($HOLD_SECONDS);"
