
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
- **Savant Host Agent**: Thin local adapter installed on the Savant host.
- **Hub config**: Pi-side configuration managed by the Web UI.
- **Host config**: Agent-side persisted config at `/usr/local/widgets-data/remotehub.json`.
- **X-Widgets-Token**: Shared token used by the Pi Hub when calling the Host Agent.
- **Savant command token**: A `sclibridge servicerequestcommand` token used to control a Savant service or zone.
