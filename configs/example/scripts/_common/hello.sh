#!/usr/bin/env bash
# Example custom script - source layout: configs/<env>/scripts/_common/.
# Deployed to /usr/local/bin/hello on every managed host.
set -euo pipefail

echo "hello from $(hostname -s)"
exit 0
