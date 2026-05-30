#!/usr/bin/env bash
set -euo pipefail
python manage.py rebuild-index "$@"

