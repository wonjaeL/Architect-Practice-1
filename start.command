#!/bin/sh
cd "$(dirname "$0")" || exit 1
python3 start.py "$@"
lab_exit_code=$?
if [ "$lab_exit_code" -ne 0 ]; then
    printf '\nPress Enter to close this window.\n'
    read -r lab_close
fi
exit "$lab_exit_code"
