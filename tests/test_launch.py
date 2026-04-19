import json as _json
import os
from datetime import datetime, timedelta
from pathlib import Path

from launch import (
    ConfigError,
    apply_env_overrides,
    apply_map_seeding,
    build_server_argv,
    load_user_config,
    run_steamcmd,
    should_validate,
    write_runtime_config,
)


def _touch(path: Path, mtime_delta: timedelta = timedelta(0)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    if mtime_delta != timedelta(0):
        past = (datetime.now() - mtime_delta).timestamp()
        os.utime(path, (past, past))


def _full_cfg():
    return {
        "bindAddress": "1.2.3.4",
        "bindPort": 9999,
        "publicAddress": "5.6.7.8",
        "publicPort": 9999,
        "a2s": {"address": "1.2.3.4", "port": 99},
        "rcon": {"address": "1.2.3.4", "port": 88, "password": "x"},
        "game": {"scenarioId": "{A}M.conf"},
    }


def test_should_validate_skip_install(tmp_path):
    binary = tmp_path / "ArmaReforgerServer"
    marker = tmp_path / "marker"
    _touch(binary)
    _touch(marker)
    assert should_validate(binary, marker, timedelta(minutes=60), skip_install=True) is False


def test_should_validate_binary_missing(tmp_path):
    binary = tmp_path / "ArmaReforgerServer"
    marker = tmp_path / "marker"
    _touch(marker)
    assert should_validate(binary, marker, timedelta(minutes=60), skip_install=False) is True


def test_should_validate_marker_missing(tmp_path):
    binary = tmp_path / "ArmaReforgerServer"
    marker = tmp_path / "marker"
    _touch(binary)
    assert should_validate(binary, marker, timedelta(minutes=60), skip_install=False) is True


def test_should_validate_marker_fresh(tmp_path):
    binary = tmp_path / "ArmaReforgerServer"
    marker = tmp_path / "marker"
    _touch(binary)
    _touch(marker)
    assert should_validate(binary, marker, timedelta(minutes=60), skip_install=False) is False


def test_should_validate_marker_stale(tmp_path):
    binary = tmp_path / "ArmaReforgerServer"
    marker = tmp_path / "marker"
    _touch(binary)
    _touch(marker, mtime_delta=timedelta(minutes=90))
    assert should_validate(binary, marker, timedelta(minutes=60), skip_install=False) is True


def test_should_validate_zero_interval_always_checks(tmp_path):
    binary = tmp_path / "ArmaReforgerServer"
    marker = tmp_path / "marker"
    _touch(binary)
    _touch(marker)
    assert should_validate(binary, marker, timedelta(0), skip_install=False) is True


def test_should_validate_marker_corrupt(tmp_path, monkeypatch):
    binary = tmp_path / "ArmaReforgerServer"
    marker = tmp_path / "marker"
    _touch(binary)
    _touch(marker)

    real_stat = Path.stat

    def broken_stat(self, *args, **kwargs):
        if self == marker:
            raise OSError("simulated failure")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", broken_stat)
    assert should_validate(binary, marker, timedelta(minutes=60), skip_install=False) is True


def test_load_user_config_missing_file(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    try:
        load_user_config(missing)
    except ConfigError as e:
        assert "not found" in str(e).lower() or "missing" in str(e).lower()
    else:
        assert False, "expected ConfigError"


def test_load_user_config_invalid_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    try:
        load_user_config(bad)
    except ConfigError as e:
        assert "parse" in str(e).lower() or "json" in str(e).lower()
    else:
        assert False, "expected ConfigError"


def test_load_user_config_missing_scenario_id(tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(_json.dumps({"game": {"name": "Test"}}))
    try:
        load_user_config(cfg)
    except ConfigError as e:
        assert "scenarioId" in str(e)
    else:
        assert False, "expected ConfigError"


def test_load_user_config_missing_game_section(tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(_json.dumps({"bindPort": 2001}))
    try:
        load_user_config(cfg)
    except ConfigError as e:
        assert "game" in str(e).lower()
    else:
        assert False, "expected ConfigError"


def test_load_user_config_valid(tmp_path):
    cfg = tmp_path / "cfg.json"
    data = {
        "bindPort": 2001,
        "game": {
            "name": "Test Server",
            "scenarioId": "{ABC}Missions/Test.conf",
        },
    }
    cfg.write_text(_json.dumps(data))
    result = load_user_config(cfg)
    assert result["game"]["scenarioId"] == "{ABC}Missions/Test.conf"
    assert result["bindPort"] == 2001


def test_apply_map_seeding_no_file(tmp_path):
    cfg = {"game": {"scenarioId": "{ABC}Missions/Fallback.conf"}}
    missing = tmp_path / "MapSeeding.json"
    apply_map_seeding(cfg, missing)
    assert cfg["game"]["scenarioId"] == "{ABC}Missions/Fallback.conf"


def test_apply_map_seeding_valid_override(tmp_path):
    cfg = {"game": {"scenarioId": "{ABC}Missions/Fallback.conf"}}
    seeding = tmp_path / "MapSeeding.json"
    seeding.write_text(_json.dumps({
        "SeedingLevel": 2,
        "MissionResourceName": "{XYZ}Missions/Next.conf",
    }))
    apply_map_seeding(cfg, seeding)
    assert cfg["game"]["scenarioId"] == "{XYZ}Missions/Next.conf"


def test_apply_map_seeding_invalid_json(tmp_path):
    cfg = {"game": {"scenarioId": "{ABC}Missions/Fallback.conf"}}
    seeding = tmp_path / "MapSeeding.json"
    seeding.write_text("{corrupt")
    apply_map_seeding(cfg, seeding)
    assert cfg["game"]["scenarioId"] == "{ABC}Missions/Fallback.conf"


def test_apply_map_seeding_missing_key(tmp_path):
    cfg = {"game": {"scenarioId": "{ABC}Missions/Fallback.conf"}}
    seeding = tmp_path / "MapSeeding.json"
    seeding.write_text(_json.dumps({"SeedingLevel": 1}))
    apply_map_seeding(cfg, seeding)
    assert cfg["game"]["scenarioId"] == "{ABC}Missions/Fallback.conf"


def test_apply_map_seeding_empty_value(tmp_path):
    cfg = {"game": {"scenarioId": "{ABC}Missions/Fallback.conf"}}
    seeding = tmp_path / "MapSeeding.json"
    seeding.write_text(_json.dumps({
        "SeedingLevel": 1,
        "MissionResourceName": "   ",
    }))
    apply_map_seeding(cfg, seeding)
    assert cfg["game"]["scenarioId"] == "{ABC}Missions/Fallback.conf"


def test_apply_map_seeding_suspicious_value(tmp_path):
    cfg = {"game": {"scenarioId": "{ABC}Missions/Fallback.conf"}}
    seeding = tmp_path / "MapSeeding.json"
    seeding.write_text(_json.dumps({
        "SeedingLevel": 1,
        "MissionResourceName": "totally-not-a-mission",
    }))
    apply_map_seeding(cfg, seeding)
    assert cfg["game"]["scenarioId"] == "{ABC}Missions/Fallback.conf"


def test_apply_env_overrides_forces_bind_address():
    cfg = _full_cfg()
    apply_env_overrides(cfg, {"GAME_PORT": "2001", "A2S_PORT": "17777", "RCON_PORT": "19999"})
    assert cfg["bindAddress"] == "0.0.0.0"
    assert cfg["a2s"]["address"] == "0.0.0.0"
    assert cfg["rcon"]["address"] == "0.0.0.0"


def test_apply_env_overrides_sets_ports():
    cfg = _full_cfg()
    apply_env_overrides(cfg, {"GAME_PORT": "2001", "A2S_PORT": "17777", "RCON_PORT": "19999"})
    assert cfg["bindPort"] == 2001
    assert cfg["publicPort"] == 2001
    assert cfg["a2s"]["port"] == 17777
    assert cfg["rcon"]["port"] == 19999


def test_apply_env_overrides_public_address_when_set():
    cfg = _full_cfg()
    apply_env_overrides(cfg, {
        "GAME_PORT": "2001", "A2S_PORT": "17777", "RCON_PORT": "19999",
        "SERVER_PUBLIC_ADDRESS": "203.0.113.42",
    })
    assert cfg["publicAddress"] == "203.0.113.42"


def test_apply_env_overrides_public_address_empty_leaves_as_is():
    cfg = _full_cfg()
    cfg["publicAddress"] = "existing.example.com"
    apply_env_overrides(cfg, {
        "GAME_PORT": "2001", "A2S_PORT": "17777", "RCON_PORT": "19999",
        "SERVER_PUBLIC_ADDRESS": "",
    })
    assert cfg["publicAddress"] == "existing.example.com"


def test_apply_env_overrides_public_address_whitespace_only_treated_as_empty():
    cfg = _full_cfg()
    cfg["publicAddress"] = "existing.example.com"
    apply_env_overrides(cfg, {
        "GAME_PORT": "2001", "A2S_PORT": "17777", "RCON_PORT": "19999",
        "SERVER_PUBLIC_ADDRESS": "   \t  ",
    })
    assert cfg["publicAddress"] == "existing.example.com"


def test_apply_env_overrides_no_a2s_section():
    cfg = _full_cfg()
    del cfg["a2s"]
    apply_env_overrides(cfg, {"GAME_PORT": "2001", "A2S_PORT": "17777", "RCON_PORT": "19999"})
    assert "a2s" not in cfg


def test_apply_env_overrides_no_rcon_section():
    cfg = _full_cfg()
    del cfg["rcon"]
    apply_env_overrides(cfg, {"GAME_PORT": "2001", "A2S_PORT": "17777", "RCON_PORT": "19999"})
    assert "rcon" not in cfg


def test_apply_env_overrides_invalid_port_raises():
    cfg = _full_cfg()
    try:
        apply_env_overrides(cfg, {"GAME_PORT": "not-a-number", "A2S_PORT": "17777", "RCON_PORT": "19999"})
    except ValueError:
        pass
    else:
        assert False, "expected ValueError for invalid port"


def test_write_runtime_config_creates_file(tmp_path):
    cfg = {"bindPort": 2001, "game": {"scenarioId": "{A}M.conf"}}
    out = tmp_path / "out.json"
    write_runtime_config(cfg, out)
    assert out.exists()
    loaded = _json.loads(out.read_text())
    assert loaded == cfg


def test_write_runtime_config_creates_parent_dirs(tmp_path):
    cfg = {"bindPort": 2001, "game": {"scenarioId": "{A}M.conf"}}
    out = tmp_path / "nested" / "dir" / "out.json"
    write_runtime_config(cfg, out)
    assert out.exists()


def test_write_runtime_config_indented_output(tmp_path):
    cfg = {"a": 1, "b": 2}
    out = tmp_path / "out.json"
    write_runtime_config(cfg, out)
    content = out.read_text()
    assert "\n" in content
    assert "  " in content


def test_build_server_argv_basic():
    argv = build_server_argv(
        binary="./ArmaReforgerServer",
        runtime_config="/tmp/runtime.json",
        profile="/profile",
        workshop="/workshop",
        arma_params="-maxFPS 120 -backendlog -nothrow",
    )
    assert argv[0] == "./ArmaReforgerServer"
    assert "-config" in argv
    assert "/tmp/runtime.json" in argv
    assert "-profile" in argv
    assert "/profile" in argv
    assert "-addonDownloadDir" in argv
    assert "-addonsDir" in argv
    assert argv.count("/workshop") == 2
    assert "-maxFPS" in argv
    assert "120" in argv
    assert "-backendlog" in argv
    assert "-nothrow" in argv


def test_build_server_argv_empty_arma_params():
    argv = build_server_argv(
        binary="./srv",
        runtime_config="/c.json",
        profile="/p",
        workshop="/w",
        arma_params="",
    )
    assert all(isinstance(a, str) and a for a in argv)


def test_build_server_argv_quoted_arma_params():
    argv = build_server_argv(
        binary="./srv",
        runtime_config="/c.json",
        profile="/p",
        workshop="/w",
        arma_params='-logLevel "high" -maxFPS 60',
    )
    assert "high" in argv
    assert "60" in argv


def test_run_steamcmd_success(monkeypatch):
    calls = []
    def mock_call(cmd):
        calls.append(cmd)
        return 0
    monkeypatch.setattr("launch.subprocess.call", mock_call)
    rc = run_steamcmd(
        steamcmd_bin=Path("/steamcmd/steamcmd.sh"),
        install_dir=Path("/reforger"),
        appid="1874900",
    )
    assert rc == 0
    assert len(calls) == 1
    cmd = calls[0]
    assert str(Path("/steamcmd/steamcmd.sh")) == cmd[0]
    assert "+force_install_dir" in cmd
    assert str(Path("/reforger")) in cmd
    assert "+login" in cmd
    assert "anonymous" in cmd
    assert "+app_update" in cmd
    assert "1874900" in cmd
    assert "validate" in cmd
    assert "+quit" in cmd


def test_run_steamcmd_failure_propagates(monkeypatch):
    def mock_call(cmd):
        return 1
    monkeypatch.setattr("launch.subprocess.call", mock_call)
    rc = run_steamcmd(
        steamcmd_bin=Path("/steamcmd/steamcmd.sh"),
        install_dir=Path("/reforger"),
        appid="1874900",
    )
    assert rc == 1