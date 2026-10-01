#!/bin/sh
# Rotates the application role's password and closes its open sessions, so
# every consumer must reconnect with the new credential.
set -e
ROTATE_ROLE=${ROTATE_ROLE:-shop_user}
echo "credential rotation starting: role=$ROTATE_ROLE db=$PGDATABASE"
until psql -tAc 'select 1' >/dev/null 2>&1; do echo "waiting for database"; sleep 2; done
NEWPW=$(head -c 24 /dev/urandom | base64 | tr -d '/+=\n')
psql -v ON_ERROR_STOP=1 -c "ALTER USER $ROTATE_ROLE WITH PASSWORD '$NEWPW';"
echo "password rotated for $ROTATE_ROLE"
n=$(psql -tAc "select count(pg_terminate_backend(pid)) from pg_stat_activity where usename='$ROTATE_ROLE' and pid<>pg_backend_pid();")
echo "closed $n open sessions for $ROTATE_ROLE; consumers must reconnect"
