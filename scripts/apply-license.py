#!/usr/bin/env python3
"""Apply a license from a Kubernetes Secret without printing the key."""
import argparse
import base64
import csv
import getpass
import io
import json
import os
import re
import subprocess
import sys


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, text=True, timeout=90, **kwargs)
    if result.returncode:
        # SQL and Kubernetes errors can include submitted license values.
        detail = re.sub(r"crl-[A-Za-z0-9+/=_-]+", "[REDACTED]", result.stderr)
        raise RuntimeError("License operation failed: " + detail.strip()[-2000:])
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", action="store_true", help="Read a new key from stdin or a hidden prompt, save it, and apply it")
    parser.add_argument("--if-present", action="store_true", help="Skip if no license Secret exists")
    args = parser.parse_args()
    kubectl = ["kubectl", "--context=" + os.environ.get("KUBE_CONTEXT", "zebu"), "-n", "cockroach"]
    if args.store:
        key = (getpass.getpass("License key: ") if sys.stdin.isatty() else sys.stdin.read()).strip()
        if not key.startswith("crl-") or any(c.isspace() for c in key):
            raise RuntimeError("Expected a single CockroachDB license key")
    else:
        raw = run(kubectl + ["get", "secret", "cockroachdb-license", "--ignore-not-found", "-o", "json"])
        if not raw.strip():
            if args.if_present:
                print("No cockroachdb-license Secret; skipping license application")
                return
            raise RuntimeError("No cockroachdb-license Secret; run with --store to provide a key")
        key = base64.b64decode(json.loads(raw)["data"]["license"]).decode().strip()
    pods = json.loads(run(kubectl + ["get", "pods", "-l", "app=cockroachdb", "-o", "json"]))["items"]
    ready = [p for p in pods if not p["metadata"].get("deletionTimestamp") and any(c["type"] == "Ready" and c["status"] == "True" for c in p.get("status", {}).get("conditions", []))]
    if not ready:
        raise RuntimeError("No Ready CockroachDB pod available")
    sql = kubectl + ["exec", "-i", ready[0]["metadata"]["name"], "-c", "cockroachdb", "--", "/cockroach/cockroach", "sql", "--certs-dir=/cockroach/cockroach-certs", "--host=localhost:26257", "--database=postgres", "--format=csv"]
    # Apply and verify before saving a new key, so invalid input cannot replace
    # a working license Secret. The setting is persisted cluster-wide in SQL.
    run(sql, input="SET CLUSTER SETTING enterprise.license = '" + key.replace("'", "''") + "';\n")
    rows = list(csv.reader(io.StringIO(run(sql, input="SHOW CLUSTER SETTING enterprise.license;\n"))))
    if len(rows) != 2 or rows[1] != [key]:
        raise RuntimeError("License readback did not match the supplied key")
    if args.store:
        secret = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "cockroachdb-license", "namespace": "cockroach"}, "type": "Opaque", "stringData": {"license": key}}
        # Server-side apply avoids copying the key into a last-applied annotation.
        run(kubectl + ["apply", "--server-side", "--field-manager=cockroach-license", "-f", "-"], input=json.dumps(secret))
    print("License applied and verified; key stored in cockroach/cockroachdb-license")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError, ValueError, subprocess.TimeoutExpired) as error:
        print(str(error) if isinstance(error, RuntimeError) else "Invalid license Secret data; details withheld", file=sys.stderr)
        sys.exit(1)
