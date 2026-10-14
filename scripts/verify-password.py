#!/usr/bin/env python3
"""Verify encrypted password connections from each application's namespace."""
import json
import os
import subprocess
import time

context = os.environ.get("KUBE_CONTEXT", "zebu")
command = ["kubectl", "--context=" + context]
for namespace in ("lunch", "horsebets", "aggrovites"):
    name = "cockroachdb-password-check-" + str(int(time.time()))
    script = '''
set -eu
/cockroach/cockroach sql --url="$DATABASE_URL" --format=csv --execute='SELECT current_database(), current_user;' </dev/null
export DATABASE_URL="$(printf '%s' "$DATABASE_URL" | sed -E 's#root:[^@]*@#root:deliberately-wrong-password@#')"
if /cockroach/cockroach sql --url="$DATABASE_URL" --execute='SELECT 1' </dev/null >/tmp/wrong-password.log 2>&1; then
  echo 'FAIL: incorrect password accepted'; exit 1
fi
grep -qi 'password authentication failed' /tmp/wrong-password.log
export DATABASE_URL="$(printf '%s' "$DATABASE_URL" | sed -E 's#root:[^@]*@#root@#')"
unset PGPASSWORD
if /cockroach/cockroach sql --url="$DATABASE_URL" --execute='SELECT 1' </dev/null >/tmp/no-password.log 2>&1; then
  echo 'FAIL: missing password accepted'; exit 1
fi
echo 'PASS: sslmode=require with saved password succeeds; incorrect and missing passwords fail'
'''
    job = {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": name, "namespace": namespace}, "spec": {"backoffLimit": 0, "activeDeadlineSeconds": 120, "ttlSecondsAfterFinished": 600, "template": {"spec": {"restartPolicy": "Never", "automountServiceAccountToken": False, "containers": [{"name": "check", "image": "cockroachdb/cockroach:v26.2.7", "command": ["/bin/sh", "-c", script], "env": [{"name": "DATABASE_URL", "valueFrom": {"secretKeyRef": {"name": "cockroachdb-connection", "key": "DATABASE_URL"}}}]}]}}}}
    result = subprocess.run(command + ["create", "-f", "-"], input=json.dumps(job), capture_output=True, text=True, check=True)
    result = subprocess.run(command + ["-n", namespace, "wait", "--for=condition=Complete", "job/" + name, "--timeout=130s"], capture_output=True, text=True)
    print(namespace + ": " + ("PASS" if result.returncode == 0 else "FAIL"), flush=True)
    # Never print raw logs: CLI connection errors may contain connection URLs.
    if result.returncode:
        raise RuntimeError("Password verification failed in " + namespace + "; inspect Job " + name + " privately")
