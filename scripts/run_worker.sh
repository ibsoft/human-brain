#!/usr/bin/env bash
set -euo pipefail
celery -A manage.celery worker --loglevel=INFO

