"""Build and check an isolated local TRIP runtime; never connect to a user instance."""
import argparse
from datetime import datetime, timezone
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
STEPS = ("docker_build", "compose_up", "backend_compile", "health", "home", "register_user", "create_trip", "read_trip", "delete_trip", "cleanup")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Use a new receipt path")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "diff", "--exit-code", "HEAD"], cwd=ROOT, check=True, capture_output=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    project = "trip-smoke-" + secrets.token_hex(6)
    receipt = {"commit": commit, "started_at": datetime.now(timezone.utc).isoformat(),
               "scope": "isolated local Docker and real HTTP; no provider requests",
               "status": "RUNNING", "checks": {step: "NOT_RUN" for step in STEPS}}
    def save():
        args.out.write_text(json.dumps(receipt, indent=2) + "\n")
    save()
    current = "docker_build"
    started = False
    with tempfile.TemporaryDirectory(prefix="trip-runtime-") as directory:
        compose = Path(directory) / "compose.json"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        compose.write_text(json.dumps({"services": {"app": {
            "image": project, "ports": [f"127.0.0.1:{port}:8000"],
            "volumes": ["sandbox:/app/storage"],
            "environment": {"REGISTER_ENABLE": "true", "OIDC_CLIENT_ID": "", "OIDC_CLIENT_SECRET": ""},
            "healthcheck": {"test": ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/info', timeout=3)"],
                            "interval": "2s", "timeout": "5s", "retries": 45}
        }}, "volumes": {"sandbox": {}}}))
        base = ["docker", "--host=unix:///var/run/docker.sock", "compose", "-p", project, "-f", str(compose)]
        # Select only this environment's local daemon; preserve registry/proxy config.
        env = {key: value for key, value in os.environ.items()
               if key not in {"DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"}}
        def run(command, step, timeout=600):
            log = args.out.parent / (args.out.stem + "-" + step + ".log")
            with log.open("w") as stream:
                result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
            if result.returncode:
                raise RuntimeError(f"{step} exit={result.returncode}; see {log.name}")
            receipt["checks"][step] = "PASS"
            save()
        def request(method, path, body=None, token=None, expected=200):
            # Hardcoded loopback socket: supplied credentials never reach an external host.
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = "Bearer " + token
            try:
                conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
                response = conn.getresponse()
                data = response.read()
                if response.status != expected:
                    raise RuntimeError(f"{method} {path} returned HTTP {response.status}")
                return data
            finally:
                conn.close()
        try:
            command = ["docker", "--host=unix:///var/run/docker.sock", "build", "-t", project]
            cert = os.environ.get("CODEX_PROXY_CERT")
            if cert:
                command += ["--secret", "id=proxy_ca,src=" + cert]
            if Path("/etc/ssl/certs/ca-certificates.crt").exists():
                command += ["--secret", "id=system_ca,src=/etc/ssl/certs/ca-certificates.crt"]
            command += ["."]
            run(command, current)
            current = "compose_up"
            started = True
            run(base + ["up", "-d", "--wait", "--wait-timeout", "120"], current, 180)
            current = "backend_compile"
            run(base + ["exec", "-T", "app", "python", "-m", "compileall", "-q", "/app/trip"], current)
            current = "health"
            assert json.loads(request("GET", "/api/info"))["version"]
            receipt["checks"][current] = "PASS"
            current = "home"
            assert b"<html" in request("GET", "/").lower()
            receipt["checks"][current] = "PASS"
            current = "register_user"
            # The application's username limit is 19 characters; Compose
            # project names use a longer prefix and cannot serve as usernames.
            username = "smoke-" + secrets.token_hex(6)
            token = json.loads(request("POST", "/api/auth/register", {"username": username, "password": secrets.token_urlsafe(32)}))["access_token"]
            receipt["checks"][current] = "PASS"
            current = "create_trip"
            name = project + " fixture"
            trip = json.loads(request("POST", "/api/trips", {"name": name, "place_ids": []}, token))
            trip_id = trip["id"]
            assert isinstance(trip_id, int) and trip["name"] == name
            receipt["checks"][current] = "PASS"
            current = "read_trip"
            read = json.loads(request("GET", f"/api/trips/{trip_id}", token=token))
            assert read["id"] == trip_id and read["name"] == name
            receipt["checks"][current] = "PASS"
            current = "delete_trip"
            request("DELETE", f"/api/trips/{trip_id}", token=token)
            request("GET", f"/api/trips/{trip_id}", token=token, expected=404)
            receipt["checks"][current] = "PASS"
            receipt["status"] = "PASS"
        except Exception as exc:
            receipt["checks"][current] = "FAIL"
            receipt.update(status="FAIL", reason=str(exc))
        finally:
            if started:
                try:
                    run(base + ["down", "--volumes", "--remove-orphans"], "cleanup", 120)
                except Exception as exc:
                    receipt.update(status="FAIL", cleanup_error=str(exc))
            receipt["completed_at"] = datetime.now(timezone.utc).isoformat()
            save()
            print(json.dumps(receipt))
    return int(receipt["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
