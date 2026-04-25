# Widgets Remote Hub Savant Host Agent

The Savant Host Agent is a thin local adapter installed on the Savant Host. For v1, the Savant Host is the Mac-based Savant Pro Host running SavantOS 11 on the LAN, not the Pi Hub. The agent exposes a small authenticated HTTP API for the Pi Hub and executes local Savant control only through `sclibridge`.

Runtime path:

```text
Pi Hub -> Savant Host Agent -> local sclibridge -> Savant
```

Widgets Cloud is control plane only. It is not part of runtime control.

## Architecture Boundary

- The Pi Hub is the product brain and config source of truth.
- The Host Agent persists last-known-good config at `/usr/local/widgets-data/remotehub.json`.
- The Host Agent does not require Pi Hub reachability at startup.
- The Host Agent keeps operating from local config while the Pi Hub is offline.
- The Host Agent never exposes generic shell execution and never calls `RunCLIProgram`.

## Install Or Update

Run from this directory on the Mac Savant Host:

```sh
sudo ./install_mac.sh
```

The installer:

- installs files to `/usr/local/widgets/remotehub/`
- creates `/usr/local/widgets-data/`
- preserves `/usr/local/widgets-data/remotehub.json`
- installs `/Library/LaunchDaemons/com.widgets.remotehub.agent.plist`
- starts or restarts `com.widgets.remotehub.agent`
- verifies `http://127.0.0.1:15001/health`

That localhost health check is correct because `install_mac.sh` runs on the Mac Savant Host. From the Pi Hub, health checks must use the Savant Host LAN IP, for example `http://10.x.x.x:15001/health`, or execute the localhost check over SSH on the Savant Host.

If no config exists yet, `/health` still works, but authenticated endpoints require a preloaded config token or `WIDGETS_AGENT_TOKEN` in the service environment. The Host Agent config does not require the Pi Hub IP.

## Uninstall

```sh
sudo ./uninstall_mac.sh
```

This unloads launchd, removes `/Library/LaunchDaemons/com.widgets.remotehub.agent.plist`, and removes `/usr/local/widgets/remotehub/`.

Host config is preserved unless explicitly requested:

```sh
sudo ./uninstall_mac.sh --remove-data
```

## Config Sync Model

v1 config is hub-push. The Pi Hub posts the complete config to:

```text
POST /config/sync
```

The agent validates the config, atomically writes `/usr/local/widgets-data/remotehub.json`, then reloads it in memory. Invalid config is rejected and does not replace the last-known-good active or disk config.

Minimum shape:

```json
{
  "version": "1.0",
  "agent": {
    "bind_host": "0.0.0.0",
    "port": 15001,
    "token": "shared-secret"
  },
  "settings": {
    "allow_test_token": false
  },
  "zones": [
    {
      "id": "living",
      "name": "Living Room",
      "states": {
        "power": "SE Living.ZoneIsActive",
        "muted": "SE Living.IsMuted",
        "volume": "SE Living.CurrentVolume",
        "active_service": "SE Living.ActiveService"
      },
      "actions": {
        "power_on": "SE Living-Sonos-Sonos_media-1-SVC_AV_SONOS-PowerOn",
        "power_off": "SE Living-----PowerOff",
        "mute_on": "SE Living-----MuteOn",
        "mute_off": "SE Living-----MuteOff",
        "volume_up": "SE Living-----VolumeUp",
        "volume_down": "SE Living-----VolumeDown"
      }
    }
  ]
}
```

## Endpoints

- `GET /health`: unauthenticated health and diagnostics
- `GET /config`: sanitized active config
- `POST /config/sync`: validate, persist, and activate full config
- `POST /config/reload`: reload local config from disk
- `GET /zones`: configured zones
- `GET /zones/{zone_id}/status`: read configured states using `sclibridge readstate`
- `POST /zones/{zone_id}/action`: execute configured action token using `sclibridge servicerequestcommand`
- `GET /savant/userzones`: run `sclibridge userzones`
- `GET /savant/services?zone=<zone>`: run `sclibridge servicesforzone <zone>`
- `POST /savant/testtoken`: execute a supplied command token only when `settings.allow_test_token` is true

All endpoints except `/health` require `X-Widgets-Token`.

## SavantOS 11 Assumptions

The confirmed SavantOS 11 `sclibridge` path is:

```text
/Users/Shared/Savant/Applications/RacePointMedia/sclibridge
```

Discovery order:

1. `/Users/Shared/Savant/Applications/RacePointMedia/sclibridge`
2. `/Users/RPM/Applications/RacePointMedia/sclibridge`
3. `PATH` lookup
4. Future Linux Smart Host detector placeholder

The runtime keeps platform hooks such as `find_sclibridge()`, `data_dir()`, and `service_manager()` so Linux Smart Host support can be added without changing the Pi/Host boundary.

## Future Linux Smart Host

Linux Smart Host support is intentionally a placeholder. The v1 package is Mac/SavantOS focused. `install_service_linux()` is stubbed until the Smart Host install path is defined.
