#!/usr/bin/env python3
"""ArmaField Linux Server - Docker entrypoint."""
import json
import os
import shlex
import signal
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping

USER_CONFIG_PATH = Path("/runtime/config.json")
MAP_SEEDING_PATH = Path("/profile/ArmaField/Systems/MapSeeding.json")
RUNTIME_CONFIG_PATH = Path(os.environ.get("RUNTIME_CONFIG", "/tmp/runtime_config.json"))
GAME_BINARY_PATH = Path("/reforger/ArmaReforgerServer")
STEAMCMD_MARKER_PATH = Path("/var/lib/armafield/steamcmd.marker")
STEAMCMD_BIN = Path("/steamcmd/steamcmd.sh")
GAME_INSTALL_DIR = Path("/reforger")

EXIT_CONFIG_ERROR = 1
EXIT_STEAMCMD_FATAL = 2


class ConfigError(Exception):
    pass


def load_user_config(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(
            f"Config file not found at {path}. "
            f"Did you `cp example_config.json config.json`?"
        )
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"Failed to parse {path}: {e}") from e

    game = cfg.get("game")
    if not isinstance(game, dict):
        raise ConfigError(f"{path}: missing or invalid 'game' section")
    if not game.get("scenarioId"):
        raise ConfigError(f"{path}: missing 'game.scenarioId'")

    return cfg


def apply_map_seeding(cfg: dict, seeding_path: Path) -> None:
    """Override cfg['game']['scenarioId'] from MapSeeding.json. Never raises."""
    if not seeding_path.exists():
        print(
            f"[info] {seeding_path} not found - using scenarioId from config.json",
            file=sys.stderr,
        )
        return

    try:
        data = json.loads(seeding_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(
            f"[warn] Failed to read {seeding_path}: {e} - "
            f"using scenarioId from config.json",
            file=sys.stderr,
        )
        return

    mission = data.get("MissionResourceName")
    if not isinstance(mission, str) or not mission.strip():
        print(
            f"[warn] {seeding_path}: 'MissionResourceName' missing or empty - "
            f"using scenarioId from config.json",
            file=sys.stderr,
        )
        return

    mission = mission.strip()
    if "{" not in mission or not mission.endswith(".conf"):
        print(
            f"[warn] {seeding_path}: 'MissionResourceName'={mission!r} "
            f"doesn't look like a scenario resource - ignoring",
            file=sys.stderr,
        )
        return

    cfg["game"]["scenarioId"] = mission
    print(f"[info] Loaded next mission from MapSeeding.json: {mission}", file=sys.stderr)


def apply_env_overrides(cfg: dict, env: Mapping[str, str]) -> None:
    """Force bind addresses to 0.0.0.0 and ports from ENV; a specific IP would break Docker networking."""
    game_port = int(env["GAME_PORT"])
    a2s_port = int(env["A2S_PORT"])
    rcon_port = int(env["RCON_PORT"])

    cfg["bindAddress"] = "0.0.0.0"
    cfg["bindPort"] = game_port
    cfg["publicPort"] = game_port

    public_addr = env.get("SERVER_PUBLIC_ADDRESS", "").strip()
    if public_addr:
        cfg["publicAddress"] = public_addr

    if isinstance(cfg.get("a2s"), dict):
        cfg["a2s"]["address"] = "0.0.0.0"
        cfg["a2s"]["port"] = a2s_port

    if isinstance(cfg.get("rcon"), dict):
        cfg["rcon"]["address"] = "0.0.0.0"
        cfg["rcon"]["port"] = rcon_port


def write_runtime_config(cfg: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def build_server_argv(
    binary: str,
    runtime_config: str,
    profile: str,
    workshop: str,
    arma_params: str,
) -> list[str]:
    return [
        binary,
        "-config", runtime_config,
        "-profile", profile,
        "-addonDownloadDir", workshop,
        "-addonsDir", workshop,
        *shlex.split(arma_params),
    ]


def run_steamcmd(steamcmd_bin: Path, install_dir: Path, appid: str) -> int:
    cmd = [
        str(steamcmd_bin),
        "+force_install_dir", str(install_dir),
        "+login", "anonymous",
        "+app_update", appid, "validate",
        "+quit",
    ]
    print(f"[info] Running SteamCMD: {shlex.join(cmd)}", file=sys.stderr, flush=True)
    return subprocess.call(cmd)


def should_validate(
    binary: Path,
    marker: Path,
    interval: timedelta,
    skip_install: bool,
) -> bool:
    if skip_install:
        return False
    if not binary.exists():
        return True
    if not marker.exists():
        return True
    try:
        last = datetime.fromtimestamp(marker.stat().st_mtime)
        if datetime.now() - last > interval:
            return True
    except Exception:
        return True
    return False


def _read_check_interval(env: Mapping[str, str]) -> timedelta:
    raw = env.get("STEAMCMD_CHECK_INTERVAL_MINUTES", "60")
    try:
        minutes = int(raw)
    except ValueError:
        print(
            f"[warn] STEAMCMD_CHECK_INTERVAL_MINUTES={raw!r} is not an integer - "
            f"using 60 minutes",
            file=sys.stderr,
        )
        minutes = 60
    return timedelta(minutes=minutes)


def main() -> int:
    env = os.environ
    skip_install = env.get("SKIP_INSTALL", "").lower() == "true"
    interval = _read_check_interval(env)

    if should_validate(GAME_BINARY_PATH, STEAMCMD_MARKER_PATH, interval, skip_install):
        rc = run_steamcmd(
            steamcmd_bin=STEAMCMD_BIN,
            install_dir=GAME_INSTALL_DIR,
            appid=env.get("STEAM_APPID", "1874900"),
        )
        if rc == 0:
            STEAMCMD_MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
            STEAMCMD_MARKER_PATH.touch()
        elif GAME_BINARY_PATH.exists():
            print(
                "[warn] SteamCMD failed but game binary exists - "
                "continuing with current version",
                file=sys.stderr,
            )
            # Don't touch marker - next launch will retry.
        else:
            print(
                f"[fatal] SteamCMD failed (exit {rc}) and no game is installed",
                file=sys.stderr,
            )
            return EXIT_STEAMCMD_FATAL

    try:
        cfg = load_user_config(USER_CONFIG_PATH)
    except ConfigError as e:
        print(f"[fatal] {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    apply_map_seeding(cfg, MAP_SEEDING_PATH)
    try:
        apply_env_overrides(cfg, env)
    except (KeyError, ValueError) as e:
        print(f"[fatal] Invalid network environment: {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    write_runtime_config(cfg, RUNTIME_CONFIG_PATH)

    argv = build_server_argv(
        binary=env.get("ARMA_BINARY", "./ArmaReforgerServer"),
        runtime_config=str(RUNTIME_CONFIG_PATH),
        profile=env.get("ARMA_PROFILE", "/profile"),
        workshop=env.get("ARMA_WORKSHOP_DIR", "/workshop"),
        arma_params=env.get("ARMA_PARAMS", "-maxFPS 120 -backendlog -nothrow"),
    )
    print(f"[info] Launching: {shlex.join(argv)}", file=sys.stderr, flush=True)

    # Register SIGTERM handler before Popen - otherwise a SIGTERM arriving in
    # the race window kills us before we can forward SIGINT to the child server.
    signal.signal(signal.SIGTERM, signal.default_int_handler)

    proc = None
    try:
        proc = subprocess.Popen(argv, cwd=str(GAME_INSTALL_DIR))
        return proc.wait()
    except KeyboardInterrupt:
        print("[info] Received stop signal - forwarding SIGINT to server", file=sys.stderr)
        if proc is not None:
            proc.send_signal(signal.SIGINT)
            return proc.wait()
        return 0
    except BaseException:
        if proc is not None:
            proc.kill()
        raise


if __name__ == "__main__":
    sys.exit(main())