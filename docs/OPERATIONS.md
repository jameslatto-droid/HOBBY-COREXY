# Operations

## Ownership and topology

The MCP is a standalone HOBBY-COREXY service, not a Brain source or Brain
filesystem tool. On the server, `tunnel-client` launches its local stdio MCP
child and exposes it to the ChatGPT connector over the supported outbound
OpenAI tunnel. The MCP itself has no network listener.

The MCP reads:

- PrusaSlicer text profiles under
  `/srv/data/3D-Printing/PrusaSlicer/production`;
- active Klipper `.cfg` includes under the configured Pi config directory,
  plus only symlink targets beneath the Pi's Mainsail and timelapse config
  directories.

It does not read `.git`, backups, `moonraker.conf`, arbitrary Pi paths, or
PrusaSlicer's app preferences for updates. SSH is pinned to the host key in
`known_hosts`. The authorized key is forced to `internal-sftp`; there is no
SSH command channel.

## Runtime configuration

The tunnel profile belongs in
`/home/james/.config/tunnel-client/jlprinter.yaml`, not Git. It references
`CONTROL_PLANE_API_KEY` through the OpenAI tunnel client's environment
reference. Use a dedicated restricted runtime key with Tunnels **Read** and
**Use** permissions, stored in
`/etc/jl-system/hobby-printer-tunnel.env`. Do not reuse the Brain tunnel's
runtime key or use an admin key for the long-lived service.

The MCP uses these optional environment variables:

| Variable | Default |
|---|---|
| `PRINTER_MCP_LOCAL_ROOT` | `/srv/data/3D-Printing/PrusaSlicer/production` |
| `PRINTER_MCP_SSH_HOST` | Required |
| `PRINTER_MCP_SSH_USER` | `pi` |
| `PRINTER_MCP_SSH_PORT` | `22` |
| `PRINTER_MCP_SSH_KEY` | `/home/james/.ssh/printer-mcp_ed25519` |
| `PRINTER_MCP_KNOWN_HOSTS` | `/home/james/.ssh/known_hosts` |
| `PRINTER_MCP_REMOTE_CONFIG_DIR` | `/home/pi/printer_data/config` |

The private key and local environment file must remain outside Git. The
deployed authorized key is restricted to SFTP, and Paramiko rejects unknown
host keys.

## Install / run

Install the project's Python dependencies in `.venv`, create a dedicated
OpenAI tunnel for this MCP, and create the private local configuration at
`/home/james/.config/hobby-printer-mcp.env` (see
`deploy/printer-mcp.env.example`). Store the dedicated runtime key as
`CONTROL_PLANE_API_KEY=...` in
`/etc/jl-system/hobby-printer-tunnel.env` using `sudoedit`; do not put it in
Git or chat. Ensure the file is root-owned with mode `600`. Then run:

```bash
sudo deploy/install-service.sh tunnel_...
```

The system installer refuses to overwrite an existing profile or service
unit. It installs and starts only this printer tunnel. Check it with:

```bash
systemctl status jl-printer-mcp-tunnel.service --no-pager
/home/james/.local/bin/tunnel-client health --listen-addr 127.0.0.1:18084
```

Add the resulting tunnel endpoint as a separate ChatGPT connector. Do not
reuse the Brain MCP client, credentials, or tunnel profile.

## Safe configuration updates

The intended sequence is `read_*` → `preview_config_update` → review the diff
→ `apply_config_update` with the returned confirmation token and
`confirmed=true`. Updates use the expected current SHA-256 to reject stale
proposals, preserve a timestamped backup, and do not reload Klipper. The
operator must separately review and reload configuration in the printer UI.

PrusaSlicer profile writes are limited to the active user `printer`,
`physical_printer`, `print`, and `filament` profile directories. Klipper
writes are limited to regular files included from `printer.cfg`; symlinked
Mainsail/timelapse files are read-only. No action tool for print, motion,
heater, or restart operations exists.

## Rollback

Stop and disable only `jl-printer-mcp-tunnel.service`. Profile/config backups
created by an explicit update remain beside their source file. Do not delete
those backups as part of service rollback.
