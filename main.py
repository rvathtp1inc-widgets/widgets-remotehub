#!/usr/bin/env python3
import json
import requests
import time

CFG_PATH = "config.json"

def load_cfg():
    with open(CFG_PATH, "r") as f:
        return json.load(f)

class HostAgent:
    def __init__(self, base_url, token):
        self.base = base_url.rstrip("/")
        self.headers = {"X-Widgets-Token": token}

    def health(self):
        r = requests.get(f"{self.base}/health", headers=self.headers, timeout=5)
        r.raise_for_status()
        return r.json()

    def status(self, zone_id):
        r = requests.get(f"{self.base}/zones/{zone_id}/status", headers=self.headers, timeout=5)
        r.raise_for_status()
        return r.json()

    def action(self, zone_id, action):
        payload = {"action": action}
        r = requests.post(
            f"{self.base}/zones/{zone_id}/action",
            headers=self.headers,
            json=payload,
            timeout=5
        )
        r.raise_for_status()
        return r.json()

def power_toggle(agent, zone_id, zone_cfg):
    st = agent.status(zone_id)
    print(f"[STATUS] {zone_id}: {st}")

    zone_active = str(st.get("zone_active", "0")) == "1"

    action = zone_cfg["off_action"] if zone_active else zone_cfg["on_action"]
    print(f"[TOGGLE] zone_active={st.get('zone_active')} -> action={action}")

    res = agent.action(zone_id, action)
    print(f"[RESULT] {res}")

def main():
    cfg = load_cfg()
    agent_cfg = cfg["host_agent"]
    zones = cfg["zones"]

    agent = HostAgent(agent_cfg["base_url"], agent_cfg["token"])

    print("[INIT] Checking host agent health...")
    print(agent.health())

    while True:
        print("\nAvailable zones:")
        for k, v in zones.items():
            print(f"  {k}: {v.get('display_name', k)}")

        zone_id = input("Zone ID (or 'q'): ").strip()
        if zone_id == "q":
            break

        if zone_id not in zones:
            print("Unknown zone")
            continue

        cmd = input("Command [power/mute/vu/vd]: ").strip()

        if cmd == "power":
            power_toggle(agent, zone_id, zones[zone_id])
        elif cmd == "mute":
            st = agent.status(zone_id)
            is_muted = str(st.get("mute", "0")) == "1"
            action = "mute_off" if is_muted else "mute_on"
            print(f"[MUTE] mute={st.get('mute')} -> action={action}")
            agent.action(zone_id, action)
        elif cmd == "vu":
            agent.action(zone_id, "vol_up")
        elif cmd == "vd":
            agent.action(zone_id, "vol_down")
        else:
            print("Unknown command")

        time.sleep(0.25)

if __name__ == "__main__":
    main()
