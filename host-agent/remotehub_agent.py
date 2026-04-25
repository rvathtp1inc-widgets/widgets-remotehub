#!/usr/bin/env python3
"""Widgets Remote Hub Savant Host Agent.

Thin local adapter for Pi Hub -> Host Agent -> local sclibridge -> Savant.
"""

import copy
import hmac
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


AGENT_VERSION = "1.0.0"
DEFAULT_BIND_HOST = "0.0.0.0"
DEFAULT_PORT = 15001
DEFAULT_TIMEOUT_SECONDS = 15
START_TIME = time.monotonic()

BOOTSTRAP_TOKEN = os.environ.get("WIDGETS_AGENT_TOKEN", "")

SCLIBRIDGE_CANDIDATES = [
    "/Users/Shared/Savant/Applications/RacePointMedia/sclibridge",
    "/Users/RPM/Applications/RacePointMedia/sclibridge",
]

STATE_BOOL_HINTS = ("power", "muted", "active", "is_", "enabled", "serviceisactive", "zoneisactive")
SENSITIVE_KEYS = {"token", "secret", "password", "api_key", "apikey"}


def service_manager():
    if sys.platform == "darwin":
        return "launchd"
    if sys.platform.startswith("linux"):
        return "systemd"
    return "unknown"


def data_dir():
    if sys.platform == "darwin":
        return Path("/usr/local/widgets-data")
    if sys.platform.startswith("linux"):
        return Path("/var/lib/widgets/remotehub")
    return Path("/usr/local/widgets-data")


def install_service_mac():
    raise NotImplementedError("Mac service installation is handled by install_mac.sh")


def install_service_linux():
    raise NotImplementedError("Linux Smart Host service installation is not implemented for v1")


DEFAULT_CONFIG_PATH = str(data_dir() / "remotehub.json")
CONFIG_PATH = Path(os.environ.get("WIDGETS_REMOTEHUB_CONFIG", DEFAULT_CONFIG_PATH))


class ConfigStore:
    def __init__(self, config_path):
        self.config_path = Path(config_path)
        self.config = None
        self.loaded = False
        self.load_error = None

    def load_from_disk(self):
        if not self.config_path.exists():
            self.config = None
            self.loaded = False
            self.load_error = "config file not found"
            return False, self.load_error

        try:
            with self.config_path.open("r", encoding="utf-8") as f:
                candidate = json.load(f)
            validate_config(candidate)
        except Exception as exc:
            self.load_error = str(exc)
            logging.exception("Failed to load config from %s", self.config_path)
            return False, self.load_error

        self.config = candidate
        self.loaded = True
        self.load_error = None
        logging.info("Loaded config version=%s zones=%s", candidate.get("version"), len(candidate.get("zones", [])))
        return True, None

    def sync(self, candidate):
        validate_config(candidate)
        atomic_write_json(self.config_path, candidate)
        self.config = candidate
        self.loaded = True
        self.load_error = None
        logging.info("Synced config version=%s zones=%s", candidate.get("version"), len(candidate.get("zones", [])))

    def token(self):
        if self.config:
            return str(self.config.get("agent", {}).get("token", ""))
        return BOOTSTRAP_TOKEN

    def bind_host(self):
        if self.config:
            return str(self.config.get("agent", {}).get("bind_host", DEFAULT_BIND_HOST))
        return os.environ.get("WIDGETS_AGENT_BIND_HOST", DEFAULT_BIND_HOST)

    def port(self):
        if self.config:
            return int(self.config.get("agent", {}).get("port", DEFAULT_PORT))
        return int(os.environ.get("WIDGETS_AGENT_PORT", DEFAULT_PORT))

    def zone_by_id(self, zone_id):
        if not self.config:
            return None
        for zone in self.config.get("zones", []):
            if zone.get("id") == zone_id:
                return zone
        return None


STORE = ConfigStore(CONFIG_PATH)


def validate_config(cfg):
    errors = []
    if not isinstance(cfg, dict):
        raise ValueError("config must be an object")

    if not cfg.get("version"):
        errors.append("version is required")

    agent = cfg.get("agent")
    if not isinstance(agent, dict):
        errors.append("agent must be an object")
    elif not agent.get("token"):
        errors.append("agent.token is required")

    if "settings" in cfg and not isinstance(cfg["settings"], dict):
        errors.append("settings must be an object")

    zones = cfg.get("zones")
    if not isinstance(zones, list):
        errors.append("zones must be a list")
        zones = []

    seen_ids = set()
    for idx, zone in enumerate(zones):
        if not isinstance(zone, dict):
            errors.append("zones[%s] must be an object" % idx)
            continue

        zone_id = zone.get("id")
        if not zone_id:
            errors.append("zones[%s].id is required" % idx)
        elif zone_id in seen_ids:
            errors.append("zone id '%s' is duplicated" % zone_id)
        else:
            seen_ids.add(zone_id)

        if not zone.get("name"):
            errors.append("zones[%s].name is required" % idx)
        if "states" in zone and not isinstance(zone["states"], dict):
            errors.append("zones[%s].states must be an object" % idx)
        if "actions" in zone and not isinstance(zone["actions"], dict):
            errors.append("zones[%s].actions must be an object" % idx)

    if errors:
        raise ValueError("; ".join(errors))


def atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".remotehub.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            logging.debug("Directory fsync skipped for %s", path.parent, exc_info=True)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def find_sclibridge():
    for candidate in SCLIBRIDGE_CANDIDATES:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("sclibridge")
    if found:
        return found
    # Future Linux Smart Host detector belongs here when that host target is defined.
    return None


def discover_sclibridge():
    return find_sclibridge()


def run_sclibridge(args):
    path = find_sclibridge()
    if not path:
        raise RuntimeError("sclibridge not found")

    cmd = [path] + args
    logging.info("Executing sclibridge: %s", redact_command(cmd))
    started = time.monotonic()
    completed = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        shell=False,
    )
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "duration_seconds": round(time.monotonic() - started, 3),
    }


def redact_command(cmd):
    if len(cmd) >= 3 and cmd[1] == "servicerequestcommand":
        return [cmd[0], cmd[1], "<savant-command-token>"]
    return cmd


def parse_json_body(handler):
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("invalid JSON body: %s" % exc)


def sanitized_config(config):
    return sanitize_value(copy.deepcopy(config))


def sanitize_value(value):
    if isinstance(value, dict):
        out = {}
        for key, child in value.items():
            lowered = str(key).lower()
            if lowered == "actions" and isinstance(child, dict):
                out[key] = {action: mask_secret(token) for action, token in child.items()}
            elif lowered in SENSITIVE_KEYS or (lowered.endswith("_token") and lowered != "allow_test_token"):
                out[key] = mask_secret(child)
            else:
                out[key] = sanitize_value(child)
        return out
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    return value


def mask_secret(value):
    if value in (None, ""):
        return ""
    text = str(value)
    if len(text) <= 8:
        return "***"
    return text[:4] + "..." + text[-4:]


def normalize_state_value(label, state_name, raw):
    text = str(raw).strip()
    lowered = text.lower()
    key = ("%s %s" % (label, state_name)).replace(".", "").replace("_", "").lower()
    looks_bool = any(hint.replace("_", "") in key for hint in STATE_BOOL_HINTS)
    if looks_bool:
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


class RemoteHubHandler(BaseHTTPRequestHandler):
    server_version = "WidgetsRemoteHubAgent/%s" % AGENT_VERSION

    def do_GET(self):
        self.route()

    def do_POST(self):
        self.route()

    def log_message(self, fmt, *args):
        logging.info("%s - %s", self.address_string(), fmt % args)

    def route(self):
        parsed = urlparse(self.path)
        path = parsed.path
        method = self.command

        try:
            if path == "/health" and method == "GET":
                self.handle_health()
                return

            if not self.is_authorized():
                self.json_response(401, {"ok": False, "error": "unauthorized"})
                return

            if path == "/config" and method == "GET":
                self.handle_get_config()
            elif path == "/config/sync" and method == "POST":
                self.handle_config_sync()
            elif path == "/config/reload" and method == "POST":
                self.handle_config_reload()
            elif path == "/zones" and method == "GET":
                self.handle_zones()
            elif path.startswith("/zones/") and path.endswith("/status") and method == "GET":
                self.handle_zone_status(path)
            elif path.startswith("/zones/") and path.endswith("/action") and method == "POST":
                self.handle_zone_action(path)
            elif path == "/savant/userzones" and method == "GET":
                self.handle_savant_userzones()
            elif path == "/savant/services" and method == "GET":
                self.handle_savant_services(parsed)
            elif path == "/savant/testtoken" and method == "POST":
                self.handle_savant_testtoken()
            else:
                self.json_response(404, {"ok": False, "error": "not found"})
        except ValueError as exc:
            self.json_response(400, {"ok": False, "error": str(exc)})
        except subprocess.TimeoutExpired:
            logging.exception("sclibridge command timed out")
            self.json_response(504, {"ok": False, "error": "sclibridge command timed out"})
        except Exception as exc:
            logging.exception("Unhandled request failure")
            self.json_response(500, {"ok": False, "error": str(exc)})

    def is_authorized(self):
        expected = STORE.token()
        if not expected:
            return False
        supplied = self.headers.get("X-Widgets-Token", "")
        return hmac.compare_digest(str(supplied), str(expected))

    def require_config(self):
        if not STORE.config:
            self.json_response(503, {"ok": False, "error": "config not loaded", "detail": STORE.load_error})
            return False
        return True

    def handle_health(self):
        sclibridge_path = find_sclibridge()
        response = {
            "ok": True,
            "agent_version": AGENT_VERSION,
            "platform": platform.platform(),
            "service_manager": service_manager(),
            "python_path": sys.executable,
            "config_path": str(STORE.config_path),
            "config_loaded": STORE.loaded,
            "sclibridge_path": sclibridge_path,
            "sclibridge_found": bool(sclibridge_path),
            "uptime_seconds": int(time.monotonic() - START_TIME),
        }
        if STORE.config and STORE.config.get("version"):
            response["config_version"] = STORE.config.get("version")
        if STORE.load_error:
            response["config_error"] = STORE.load_error
        self.json_response(200, response)

    def handle_get_config(self):
        if not self.require_config():
            return
        self.json_response(200, {"ok": True, "config": sanitized_config(STORE.config)})

    def handle_config_sync(self):
        candidate = parse_json_body(self)
        validate_config(candidate)
        STORE.sync(candidate)
        self.json_response(200, {"ok": True, "config_path": str(STORE.config_path), "config_version": candidate.get("version")})

    def handle_config_reload(self):
        ok, err = STORE.load_from_disk()
        code = 200 if ok else 500
        self.json_response(code, {"ok": ok, "config_path": str(STORE.config_path), "error": err})

    def handle_zones(self):
        if not self.require_config():
            return
        zones = []
        for zone in STORE.config.get("zones", []):
            zones.append({
                "id": zone.get("id"),
                "name": zone.get("name"),
                "states": sorted((zone.get("states") or {}).keys()),
                "actions": sorted((zone.get("actions") or {}).keys()),
            })
        self.json_response(200, {"ok": True, "zones": zones})

    def handle_zone_status(self, path):
        if not self.require_config():
            return
        zone_id = self.extract_zone_id(path, "status")
        zone = STORE.zone_by_id(zone_id)
        if not zone:
            self.json_response(404, {"ok": False, "error": "unknown zone"})
            return

        states = zone.get("states") or {}
        values = {}
        ok = True
        for label, state_name in states.items():
            result = run_sclibridge(["readstate", str(state_name)])
            raw = result.get("stdout", "")
            if not result["ok"]:
                ok = False
            values[label] = {
                "state": state_name,
                "raw": raw,
                "value": normalize_state_value(label, state_name, raw),
                "ok": result["ok"],
                "returncode": result["returncode"],
                "stderr": result["stderr"],
            }
        code = 200 if ok else 502
        self.json_response(code, {"ok": ok, "zone_id": zone_id, "status": values})

    def handle_zone_action(self, path):
        if not self.require_config():
            return
        zone_id = self.extract_zone_id(path, "action")
        zone = STORE.zone_by_id(zone_id)
        if not zone:
            self.json_response(404, {"ok": False, "error": "unknown zone"})
            return

        body = parse_json_body(self)
        action = body.get("action")
        if not action:
            self.json_response(400, {"ok": False, "error": "action is required"})
            return
        token = (zone.get("actions") or {}).get(action)
        if not token:
            self.json_response(404, {"ok": False, "error": "unknown action"})
            return

        logging.info("Executing configured action zone=%s action=%s", zone_id, action)
        result = run_sclibridge(["servicerequestcommand", str(token)])
        code = 200 if result["ok"] else 502
        self.json_response(code, {"ok": result["ok"], "zone_id": zone_id, "action": action, "result": result})

    def handle_savant_userzones(self):
        result = run_sclibridge(["userzones"])
        code = 200 if result["ok"] else 502
        self.json_response(code, {"ok": result["ok"], "result": result})

    def handle_savant_services(self, parsed):
        params = parse_qs(parsed.query)
        zone = params.get("zone", [""])[0]
        if not zone:
            self.json_response(400, {"ok": False, "error": "zone query parameter is required"})
            return
        result = run_sclibridge(["servicesforzone", zone])
        code = 200 if result["ok"] else 502
        self.json_response(code, {"ok": result["ok"], "zone": zone, "result": result})

    def handle_savant_testtoken(self):
        if not self.require_config():
            return
        settings = STORE.config.get("settings") or {}
        if settings.get("allow_test_token") is not True:
            self.json_response(403, {"ok": False, "error": "test token execution disabled"})
            return
        body = parse_json_body(self)
        token = body.get("token")
        if not token:
            self.json_response(400, {"ok": False, "error": "token is required"})
            return
        logging.warning("Executing test Savant command token via /savant/testtoken")
        result = run_sclibridge(["servicerequestcommand", str(token)])
        code = 200 if result["ok"] else 502
        self.json_response(code, {"ok": result["ok"], "result": result})

    def extract_zone_id(self, path, suffix):
        prefix = "/zones/"
        end = "/" + suffix
        return unquote(path[len(prefix):-len(end)])

    def json_response(self, status, payload):
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def configure_logging():
    logging.basicConfig(
        level=os.environ.get("WIDGETS_AGENT_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )


def main():
    configure_logging()
    STORE.load_from_disk()
    host = STORE.bind_host()
    port = STORE.port()
    server = ThreadingHTTPServer((host, port), RemoteHubHandler)
    logging.info("Widgets Remote Hub Agent %s listening on %s:%s", AGENT_VERSION, host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
