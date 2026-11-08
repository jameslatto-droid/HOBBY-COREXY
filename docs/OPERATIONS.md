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
  directories; opt-in `include_unreferenced=true` on list/read also exposes
  staged `.cfg` files directly in that config directory.

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
/home/james/.local/bin/tunnel-client health --url http://127.0.0.1:18084 --require-control-plane-poll
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

### Create and delete

Use `preview_config_create` then `apply_config_create` with identical target,
category, filename, content, the returned token, and `confirmed=true`.
Creation supports only new `.ini` files in the four user-profile directories
or new plain `.cfg` files directly in the Pi config directory. Creation is
exclusive: it cannot replace an existing file or symlink. New Klipper files
must be unreferenced, including by wildcard includes; creation never changes
`printer.cfg`, adds an include, or restarts Klipper. Profiles become visible
to PrusaSlicer but are not selected by this service.

For a new Klipper file, list/read with `include_unreferenced=true`. The
default list/read remains active-includes-only. Existing replacement tools
remain restricted to active includes: review and explicitly add the include
before using them for a staged Klipper file.

For deletion, first read the file, then use `preview_config_delete` and
`apply_config_delete` with the current SHA-256, returned token, and
`confirmed=true`. Deletion is restricted to `.ini` user profiles and
unreferenced regular Klipper `.cfg` files. `printer.cfg`, files referenced by
any directly listed config (including inactive configs and wildcard
includes), symlinks, app/vendor files, backups, and files with secret-like
settings are protected. Remove references explicitly before proposing a
Klipper deletion. Both locations retain and verify a timestamped backup
before deleting the original.

Create/delete tokens are random, bound to the exact operation and content
hash, expire after ten minutes, and are consumed by an apply attempt.
Restarting the MCP invalidates pending previews. Failed applies need a new
preview; inspect the current file first. Backups retained on failure are
intentional recovery evidence, not success.

Do not edit the same files concurrently in PrusaSlicer, the printer UI, or
another client. Hash/reference checks reject observed drift but are not
distributed filesystem locks.

After a code update, restart only `jl-printer-mcp-tunnel.service` and refresh
the ChatGPT connector catalogue to discover new tools. This does not restart
Klipper.

## Rollback

Stop and disable only `jl-printer-mcp-tunnel.service`. Profile/config backups
created by an explicit update remain beside their source file. Do not delete
those backups as part of service rollback.
