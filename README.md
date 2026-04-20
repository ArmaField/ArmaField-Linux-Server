# ArmaField-Linux-Server

Docker-based Arma Reforger dedicated server for Linux with native support for
the [ArmaField](https://reforger.armaplatform.com/workshop/68FA258A6C74CE73-ArmaField) mod's MapSeeding
rotation mechanic.

- Auto-installs and updates the game via SteamCMD
- Reads your `config.json`
- Detects the next mission from the mod's `MapSeeding.json` between rounds
- Clean restart between missions via Docker restart policy

## Requirements

- Linux host with Docker and Docker Compose v2
- At least 4 GB RAM free (6 GB recommended)
- At least 15 GB free disk (game files are ~10 GB, plus mods)
- 1 Gbps (1000 Mbit/s) upload bandwidth
- A public IP or port forwarding to one of the server ports

## Quick start

```bash
git clone https://github.com/ArmaField/ArmaField-Linux-Server.git
cd ArmaField-Linux-Server

cp .env.example .env
cp example_config.json config.json

# Edit .env:
#   - SERVER_PUBLIC_ADDRESS - your public IPv4.
#   - GAME_PORT / A2S_PORT / RCON_PORT - change to your preferred ports if the
# Edit config.json:
#   - game.passwordAdmin, rcon.password - change from CHANGEME.
#   - game.name - server name shown in the browser.
#   - game.maxPlayers - player slot count (default 64).
#   - game.admins - your Steam IDs for in-game admin access.
#   - game.mods - add/remove Workshop mods.
#   - game.gameProperties - view distance, BattlEye, third-person, etc.

docker compose up -d
docker compose logs -f
```

The first launch downloads ~10 GB of game files via SteamCMD - expect
5-10 minutes before the server is ready.

> **ArmaField mod backend:** for anything beyond local testing, set your
> `ServerToken` and `BackendURL` in `profile/profile/ArmaField/Systems/BackendSettings.json`
> - see [ArmaField mod: backend configuration](#armafield-mod-backend-configuration).
> Note the **double `profile/`** - ArmaReforgerServer creates a `profile/` subdirectory
> inside the profile path we give it, so the mod's files land one level deeper than you might expect.

**Before opening the server to players, make sure your chosen UDP ports are open at every layer:**

1. **Host firewall** (UFW / firewalld / iptables) - see [Firewall](#firewall) below.
2. **Cloud security groups** (AWS, Hetzner, DigitalOcean, etc.) - allow the same UDP ports in your provider's panel.
3. **Hosting provider Anti-DDoS panel** (OVH Game Firewall, Path.net, Hetzner vSwitch rules, etc.) - if your host has one, whitelist the same UDP ports there. Otherwise legitimate Arma Reforger UDP traffic gets classified as "suspicious" and dropped, clients can't connect even though everything else is correct.

## Configuration files

Two files control your server:

| File | Purpose |
|---|---|
| `.env` | Network settings (ports, public address), startup flags, update policy |
| `config.json` | Server content settings: name, passwords, mods, scenario, admins |

Templates (`.env.example`, `example_config.json`) are in git and contain sensible defaults.

### `.env` reference

| Variable | Default | Meaning |
|---|---|---|
| `SERVER_PUBLIC_ADDRESS` | *(empty)* | Public IPv4 address players see. Required for public servers. |
| `GAME_PORT` | `2001` | UDP port for client connections. |
| `A2S_PORT` | `17777` | UDP port for Steam server-query. |
| `RCON_PORT` | `19999` | UDP port for RCON (only used if `rcon` section is in `config.json`). |
| `ARMA_PARAMS` | `-maxFPS 120 -backendlog -nothrow` | Server startup flags. [Full list](https://community.bistudio.com/wiki/Arma_Reforger:Startup_Parameters). |
| `STEAMCMD_CHECK_INTERVAL_MINUTES` | `60` | Minutes between SteamCMD update checks. `0` = every launch. |
| `SKIP_INSTALL` | `false` | Skip update checks entirely (for maintenance). |

### `config.json` reference

See the [Bohemia Interactive Server Config wiki page](https://community.bistudio.com/wiki/Arma_Reforger:Server_Config).

**Fields forced by the container (do not rely on your `config.json` values for these):**
- `bindAddress` - always `0.0.0.0` inside the container
- `a2s.address`, `rcon.address` - always `0.0.0.0`
- `bindPort`, `publicPort` - from `GAME_PORT`
- `a2s.port` - from `A2S_PORT`
- `rcon.port` - from `RCON_PORT`
- `publicAddress` - from `SERVER_PUBLIC_ADDRESS` (if non-empty)
- `game.scenarioId` - from `MapSeeding.json` (if present and valid), otherwise kept as you set it

## Firewall

Open the same UDP ports on your host firewall.

> **Use your own port values.** The commands below show the defaults (`2001`, `17777`, `19999`). If you changed `GAME_PORT`, `A2S_PORT`, or `RCON_PORT` in `.env`, substitute those numbers instead - otherwise the firewall will open the wrong ports and your server will be unreachable.

**Ubuntu / Debian (UFW):**
```bash
sudo ufw allow 2001/udp
sudo ufw allow 17777/udp
sudo ufw allow 19999/udp
```

**RHEL / Fedora (firewalld):**
```bash
sudo firewall-cmd --permanent --add-port=2001/udp
sudo firewall-cmd --permanent --add-port=17777/udp
sudo firewall-cmd --permanent --add-port=19999/udp
sudo firewall-cmd --reload
```

**iptables:**
```bash
sudo iptables -A INPUT -p udp --dport 2001 -j ACCEPT
sudo iptables -A INPUT -p udp --dport 17777 -j ACCEPT
sudo iptables -A INPUT -p udp --dport 19999 -j ACCEPT
```

**Note:** Docker on Linux manipulates iptables directly and bypasses UFW -
ports published via `docker-compose.yml` may be reachable even when UFW
blocks them. Cloud providers (AWS, Hetzner, DigitalOcean, etc.) have
separate security-group firewalls that you must configure in their control
panels.

## MapSeeding: how the mod rotation works

After each mission, the ArmaField mod writes the next mission's scenario ID
to `profile/profile/ArmaField/Systems/MapSeeding.json`:

```json
{
    "SeedingLevel": 1,
    "MissionResourceName": "{1FB87580B53C498D}Missions/AF_Arland_Airport.conf"
}
```

The server process then exits, the container exits, Docker restarts the
container per the `restart: unless-stopped` policy, and `launch.py` reads the
updated file to pick the next mission's `scenarioId` before re-launching the
server.

If `MapSeeding.json` is missing (first launch) or invalid, the container
falls back to the `scenarioId` set in your `config.json` - so your initial
`config.json` value is effectively the starting mission.

## ArmaField mod: backend configuration

The ArmaField mod connects to an ArmaField backend for match statistics, player
identity, and other cross-server features. The mod reads its backend settings
from `profile/profile/ArmaField/Systems/BackendSettings.json`.

> **Why the double `profile/`?** ArmaReforgerServer creates a `profile/`
> subdirectory inside whatever directory we pass via `-profile`, so the mod's
> files land at `profile/profile/ArmaField/Systems/` on the host - right next
> to `MapSeeding.json` written by the mod between missions.

Create (or edit) this file **before** starting the server:

```bash
mkdir -p profile/profile/ArmaField/Systems
nano profile/profile/ArmaField/Systems/BackendSettings.json
```

File content:

```json
{
    "ServerToken": "YOUR-SERVER-TOKEN",
    "BackendURL": "https://your.backend.url"
}
```

> **`BackendURL` MUST be HTTPS with a valid SSL certificate.** Arma Reforger
> rejects plain HTTP outright - `http://...` URLs will not work even for local
> testing. If you self-host the backend, put it behind a reverse proxy with a
> Let's Encrypt cert (Caddy, Traefik, Nginx + Certbot - any of them) before
> pointing the mod at it.

**Defaults** (test backend - use only for local development or testing, not for public play):

```json
{
    "ServerToken": "ARMAFIELD-TEST-TOKEN",
    "BackendURL": "https://test.armafield.gg"
}
```

For production you must **self-host the backend** - there is no free public
backend to connect to. The open-source backend can be found at [ArmaField BackEnd Repository](https://github.com/ArmaField/ArmaField-BackEnd).

**Without a reachable backend the ArmaField mod does not function at all** -
the spawn menu may fail to open and players will not be able to spawn into the
match. A working HTTPS backend with a valid `ServerToken` is a hard requirement
for the mod to run, not an optional add-on for stats.

Since `profile/` is a bind-mounted volume, the file persists between container
rebuilds - you only need to set it up once per host.

## Update policy

On each container start, the launcher decides whether to run
`steamcmd validate` based on a marker file stored in the container's writable
layer:

- **First launch ever** (game binary missing): always installs.
- **Fresh container** (`docker compose down && up`): always validates.
- **Auto-restart between missions** (< `STEAMCMD_CHECK_INTERVAL_MINUTES`
  since last check): skips the check for faster mission rotation.
- **Auto-restart after a long idle period**: validates to catch updates.

If SteamCMD fails (e.g., Steam is down) but the game is already installed,
the server starts with the current version and prints a warning - no outage.
The next launch retries.

## Troubleshooting

**Logs:**
```bash
docker compose logs -f
```

**Server files on the host:**
- `./profile/` - server logs, MapSeeding.json, crash dumps
- `./workshop/` - downloaded mod files
- Docker-managed volume `reforger-data` - game files (location: `docker volume inspect <project>_reforger-data`)

**Force a clean reinstall of the game:**
```bash
docker compose down --volumes
docker compose up -d
```

**Clients can't connect:**
1. Verify `SERVER_PUBLIC_ADDRESS` in `.env` is correct.
2. Verify firewall: `sudo ufw status` or `sudo iptables -L -n`.
3. Check port forwarding on your router if behind NAT.
4. Run `docker compose logs | grep -i 'register\|listen\|bind'` and look for errors.

## Development

**Run tests:**
```bash
pip install -r requirements-dev.txt
pytest
```

**Build the image locally:**
```bash
docker build -t armafield-linux-server:dev .
```

## License

[MIT](./LICENSE) © ARMAFIELD