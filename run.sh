#!/bin/zsh
# Entry point used by launchd (and handy manually): ./run.sh [run|list|open] [args]
cd "$(dirname "$0")"
mkdir -p data
exec /usr/bin/env python3 ainews.py "${@:-run}"
