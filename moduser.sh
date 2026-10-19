#!/usr/bin/env bash
set -euo pipefail
[[ $# == 1 ]] || exit 1
printf '%s' "$1" | /scripts/reset-password.py
