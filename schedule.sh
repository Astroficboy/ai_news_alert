#!/bin/zsh
# Install / remove the background jobs (macOS launchd).
#   ./schedule.sh install [minutes]   news updates every N minutes (default 360)
#   ./schedule.sh uninstall
#   ./schedule.sh ui-install          keep the reader app running at http://localhost:8790
#   ./schedule.sh ui-uninstall
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"

# write_plist LABEL EXTRA_KEYS ARGS...
write_plist() {
  local label=$1 extra=$2; shift 2
  local args="" a
  for a in "$@"; do args+="<string>$a</string>"; done
  mkdir -p "$AGENTS" "$DIR/data"
  cat > "$AGENTS/$label.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array>$args</array>
  $extra
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string></dict>
  <key>StandardOutPath</key><string>$DIR/data/${label##*.}.log</string>
  <key>StandardErrorPath</key><string>$DIR/data/${label##*.}.log</string>
</dict></plist>
EOF
  launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
  launchctl bootstrap "$DOMAIN" "$AGENTS/$label.plist"
}

remove() {
  launchctl bootout "$DOMAIN/$1" 2>/dev/null || true
  rm -f "$AGENTS/$1.plist"
  echo "Removed $1"
}

case "${1:-install}" in
  install)
    MIN=${2:-360}
    write_plist "com.$USER.ainews" "<key>StartInterval</key><integer>$(( MIN * 60 ))</integer><key>RunAtLoad</key><true/>" \
      "$DIR/run.sh" run
    echo "Installed: news updates every $MIN min. Log: $DIR/data/ainews.log"
    ;;
  uninstall) remove "com.$USER.ainews" ;;
  ui-install)
    write_plist "com.$USER.ainews-ui" "<key>KeepAlive</key><true/><key>RunAtLoad</key><true/>" \
      "$DIR/run.sh" ui --no-browser
    echo "Installed: reader app always running at http://localhost:8790. Log: $DIR/data/ainews-ui.log"
    ;;
  ui-uninstall) remove "com.$USER.ainews-ui" ;;
  *) echo "usage: $0 install [minutes] | uninstall | ui-install | ui-uninstall"; exit 1 ;;
esac
