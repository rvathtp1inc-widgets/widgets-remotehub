
## Current Repo Role

This repo currently represents the Pi-side prototype/control UI for the Widgets Roku/Xfinity Remote → Savant Control Hub.

It should not be treated as the final Savant Host Agent package yet.

The intended v1 architecture is:

Pi Hub Web UI / config source of truth
→ installs/updates thin Savant Host Agent over SSH
→ pushes config to Host Agent via `/config/sync`
→ Host Agent executes local Savant commands through `sclibridge`

Runtime Savant control remains local. Widgets Cloud is control-plane only.

## Terminology

- **Pi Hub**: The product brain, installer UI, config owner, and future cloud-registered hub.
- **Savant Host**: The Savant controller machine that runs the Host Agent. The current v1 target is a Mac-based Savant Pro Host running SavantOS 11.
- **Savant Host Agent**: Thin local adapter installed on the Savant Host, not on the Pi Hub.
- **Hub config**: Pi-side configuration managed by the Web UI.
- **Host config**: Agent-side persisted config at `/usr/local/widgets-data/remotehub.json`.
- **X-Widgets-Token**: Shared token used by the Pi Hub when calling the Host Agent.
- **Savant command token**: A `sclibridge servicerequestcommand` token used to control a Savant service or zone.

## Addressing Rule

`127.0.0.1` only points at the machine executing the command.

- From the Savant Host itself, `curl http://127.0.0.1:15001/health` is valid.
- From the Pi Hub, Host Agent health must use the Savant Host LAN address, for example `curl http://10.x.x.x:15001/health`.
- From the Pi Hub, a localhost health check is only valid when executed over SSH on the Savant Host, for example `ssh user@10.x.x.x 'curl http://127.0.0.1:15001/health'`.

Pi-side config stores `host_agent.base_url` as a LAN URL such as `http://10.x.x.x:15001`. The Host Agent config does not require the Pi Hub IP.

Future Linux-based Smart Hosts should fit behind the platform abstraction hooks in the Host Agent package. They are not the current install target.
