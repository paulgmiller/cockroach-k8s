#!/usr/bin/env python3
"""Create the persistent root bootstrap Secret once; never print credentials."""
import base64
import json
import os
import secrets
import subprocess
import sys


def ensure_root_secret(context, namespace="cockroach"):
    command = ["kubectl", "--context=" + context, "-n", namespace]
    result = subprocess.run(command + ["get", "secret", "cockroachdb-root", "--ignore-not-found", "-o", "json"], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Cannot read root Secret; check Kubernetes access")
    if result.stdout.strip():
        data = json.loads(result.stdout)["data"]
        password = base64.b64decode(data["password"]).decode()
        sql = base64.b64decode(data["init.sql"]).decode()
        expected = "ALTER USER root WITH PASSWORD '" + password.replace("'", "''") + "';\n"
        if not password or sql != expected:
            raise RuntimeError("Existing root Secret has inconsistent password/bootstrap SQL; refusing to replace it")
        print("Reusing cockroach/cockroachdb-root", flush=True)
        return password
    cluster = subprocess.run(command + ["get", "crdbcluster", "cockroachdb-secure", "--ignore-not-found", "-o", "json"], capture_output=True, text=True)
    if cluster.returncode:
        raise RuntimeError("Cannot inspect cluster before generating credentials")
    if cluster.stdout.strip() and any(c["type"] == "Initialized" and c["status"] == "True" for c in json.loads(cluster.stdout).get("status", {}).get("conditions", [])):
        raise RuntimeError("Root Secret is missing for an initialized cluster; restore it instead of generating a different password")
    password = secrets.token_urlsafe(48)
    obj = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "cockroachdb-root", "namespace": namespace}, "type": "Opaque", "stringData": {"password": password, "init.sql": "ALTER USER root WITH PASSWORD '" + password + "';\n"}}
    result = subprocess.run(command + ["create", "-f", "-"], input=json.dumps(obj), capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Cannot create root Secret; no credentials were printed")
    print("Created cockroach/cockroachdb-root with a random password", flush=True)
    return password


if __name__ == "__main__":
    try:
        ensure_root_secret(os.environ.get("KUBE_CONTEXT", "zebu"))
    except (RuntimeError, KeyError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
