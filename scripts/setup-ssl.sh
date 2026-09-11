#!/usr/bin/env bash
# Retired: the previous script overwrote tracked nginx configuration and did not
# mount certificates into the container. Use the explicit edge compose instead.
set -euo pipefail
cat >&2 <<'MSG'
Use docker-compose.edge.yml with the production compose after configuring
ATOM_DOMAIN, DNS, firewall and ALLOWED_ORIGINS. See docs/PILOT-DEPLOYMENT.md.
This command makes no changes to the server.
MSG
exit 2
