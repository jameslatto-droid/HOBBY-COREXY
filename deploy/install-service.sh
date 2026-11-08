#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TUNNEL_ID="${1:-}"
PROFILE_DIR="/home/james/.config/tunnel-client"
PROFILE_PATH="$PROFILE_DIR/jlprinter.yaml"
SERVICE_PATH="/etc/systemd/system/jl-printer-mcp-tunnel.service"
LOCAL_ENV="/home/james/.config/hobby-printer-mcp.env"

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo $0 <dedicated-printer-tunnel-id>" >&2
  exit 1
fi
if [[ ! "$TUNNEL_ID" =~ ^tunnel_([a-z0-9]{32}|[a-z0-9]{4}_[a-z0-9]{32})$ ]]; then
  echo "Pass the dedicated printer tunnel ID (tunnel_...)." >&2
  exit 1
fi
[[ -x "$REPO_ROOT/.venv/bin/hobby-printer-mcp" ]] || {
  echo "Install the project first: $REPO_ROOT/.venv/bin/pip install -e $REPO_ROOT" >&2
  exit 1
}
[[ -x /home/james/.local/bin/tunnel-client ]] || {
  echo "Missing tunnel-client at /home/james/.local/bin/tunnel-client" >&2
  exit 1
}
[[ -r /etc/jl-system/hobby-printer-tunnel.env ]] || {
  echo "Missing restricted runtime tunnel environment: /etc/jl-system/hobby-printer-tunnel.env" >&2
  exit 1
}
if [[ -L /etc/jl-system/hobby-printer-tunnel.env ]] ||
  [[ "$(stat -c '%U:%a' /etc/jl-system/hobby-printer-tunnel.env)" != "root:600" ]]; then
  echo "Runtime tunnel environment must be a root-owned regular file with mode 600." >&2
  exit 1
fi
[[ -r "$LOCAL_ENV" ]] || {
  echo "Missing local printer MCP configuration: $LOCAL_ENV" >&2
  exit 1
}
[[ -r /home/james/.ssh/printer-mcp_ed25519 ]] || {
  echo "Missing restricted printer MCP SSH key." >&2
  exit 1
}
[[ ! -e "$PROFILE_PATH" ]] || {
  echo "Refusing to overwrite existing tunnel profile: $PROFILE_PATH" >&2
  exit 1
}
[[ ! -e "$SERVICE_PATH" ]] || {
  echo "Refusing to overwrite existing service unit: $SERVICE_PATH" >&2
  exit 1
}

install -d -o james -g james -m 0700 "$PROFILE_DIR"
umask 077
sed \
  -e "s|@@TUNNEL_ID@@|$TUNNEL_ID|g" \
  -e "s|@@MCP_COMMAND@@|$REPO_ROOT/.venv/bin/hobby-printer-mcp|g" \
  "$REPO_ROOT/deploy/tunnel-client/jlprinter.yaml.in" |
  install -o james -g james -m 0600 /dev/stdin "$PROFILE_PATH"
sed \
  -e "s|@@REPO_ROOT@@|$REPO_ROOT|g" \
  "$REPO_ROOT/deploy/systemd/jl-printer-mcp-tunnel.service.in" |
  install -o root -g root -m 0644 /dev/stdin "$SERVICE_PATH"

systemctl daemon-reload
systemctl enable --now jl-printer-mcp-tunnel.service
systemctl is-active --quiet jl-printer-mcp-tunnel.service

attempts=0
while ((attempts < 30)); do
  if command -v ss >/dev/null 2>&1 &&
    ss -ltn 2>/dev/null | awk '{print $4}' | grep -Fxq '127.0.0.1:18084'; then
    echo "PASS: printer MCP tunnel system service is active."
    echo "Unit: $SERVICE_PATH"
    echo "Profile: $PROFILE_PATH"
    exit 0
  fi
  attempts=$((attempts + 1))
  sleep 1
done

echo "Tunnel health listener is not bound to 127.0.0.1:18084." >&2
systemctl stop jl-printer-mcp-tunnel.service
exit 1
