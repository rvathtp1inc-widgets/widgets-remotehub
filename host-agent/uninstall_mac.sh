#!/bin/sh
set -eu

LABEL="com.widgets.remotehub.agent"
INSTALL_DIR="/usr/local/widgets/remotehub"
DATA_DIR="/usr/local/widgets-data"
PLIST_DST="/Library/LaunchDaemons/${LABEL}.plist"
REMOVE_DATA=0

case "${1:-}" in
  --reset|--remove-data)
    REMOVE_DATA=1
    ;;
  "" )
    ;;
  * )
    echo "Usage: $0 [--reset|--remove-data]" >&2
    exit 1
    ;;
esac

if [ "$(id -u)" -ne 0 ]; then
  echo "uninstall_mac.sh must be run as root" >&2
  exit 1
fi

if launchctl print "system/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout system "$PLIST_DST" >/dev/null 2>&1 || true
fi

rm -f "$PLIST_DST"
rm -rf "$INSTALL_DIR"

if [ "$REMOVE_DATA" -eq 1 ]; then
  rm -f "${DATA_DIR}/remotehub.json"
  rmdir "$DATA_DIR" >/dev/null 2>&1 || true
  echo "Removed agent files and host config data"
else
  echo "Removed agent files; preserved ${DATA_DIR}/remotehub.json"
fi
