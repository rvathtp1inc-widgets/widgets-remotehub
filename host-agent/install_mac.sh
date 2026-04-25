#!/bin/sh
set -eu

LABEL="com.widgets.remotehub.agent"
INSTALL_DIR="/usr/local/widgets/remotehub"
DATA_DIR="/usr/local/widgets-data"
PLIST_SRC="./com.widgets.remotehub.agent.plist"
PLIST_DST="/Library/LaunchDaemons/${LABEL}.plist"
HEALTH_URL="http://127.0.0.1:15001/health"

if [ "$(id -u)" -ne 0 ]; then
  echo "install_mac.sh must be run as root" >&2
  exit 1
fi

cd "$(dirname "$0")"

choose_python() {
  if [ -x "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python" ]; then
    echo "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python"
  elif [ -x "/usr/bin/python3" ]; then
    echo "/usr/bin/python3"
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  else
    echo "python3 not found" >&2
    exit 1
  fi
}

PYTHON_PATH="$(choose_python)"

mkdir -p "$INSTALL_DIR" "$INSTALL_DIR/logs" "$DATA_DIR"
install -m 0755 remotehub_agent.py "$INSTALL_DIR/remotehub_agent.py"
install -m 0644 README.md "$INSTALL_DIR/README.md"

TMP_PLIST="$(mktemp "/tmp/${LABEL}.plist.XXXXXX")"
sed "s#__PYTHON_PATH__#${PYTHON_PATH}#g" "$PLIST_SRC" > "$TMP_PLIST"
install -m 0644 "$TMP_PLIST" "$PLIST_DST"
rm -f "$TMP_PLIST"
chown root:wheel "$PLIST_DST" 2>/dev/null || chown root:root "$PLIST_DST"

if launchctl print "system/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout system "$PLIST_DST" >/dev/null 2>&1 || true
fi

launchctl bootstrap system "$PLIST_DST"
launchctl enable "system/${LABEL}"
launchctl kickstart -k "system/${LABEL}"

echo "Installed ${LABEL} using ${PYTHON_PATH}"
echo "Preserved config path: ${DATA_DIR}/remotehub.json"

sleep 2
if command -v curl >/dev/null 2>&1; then
  curl -fsS "$HEALTH_URL"
  echo
else
  echo "curl not found; skipping health verification"
fi
