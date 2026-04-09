# PRTG Network Monitor MCP Server

An MCP server exposing 41 tools for PRTG Network Monitor, wrapping both the REST API v2 (experimental endpoints) and the classic v1 API. Provides full read and (optionally) write access to your monitoring environment through Claude Code.

---

## Tool Summary

| Category | Count | Requires write mode | Tools |
|---|---|---|---|
| **V2 Read** | 14 | no | `list_probes`, `list_groups`, `list_devices`, `list_sensors`, `list_objects`, `list_channels`, `list_users`, `list_user_groups`, `get_user`, `get_user_group`, `get_license_info`, `get_device_templates`, `get_child_object_types`, `get_timeseries` |
| **V1 Read** | 2 | no | `query_table`, `get_historic_data` |
| **Convenience** | 2 | no | `get_problem_sensors`, `get_device_health` |
| **V1 Operational** | 8 | yes | `pause_object`, `pause_object_for`, `resume_object`, `acknowledge_alarm`, `scan_now`, `simulate_error`, `auto_discovery`, `test_notification` |
| **V1 Management** | 7 | yes | `rename_object`, `set_object_property`, `set_priority`, `clone_object`, `set_position`, `set_geo_location`, `add_to_report` |
| **V2 Write** | 7 | yes | `create_group`, `create_device`, `create_sensor`, `update_sensor`, `move_object`, `delete_object`, `trigger_metascan` |
| **Server** | 1 | no | `reload_prtg_impl` (hot-reload `prtg_impl.py` without restarting the MCP server) |

**Totals:** 18 read-only · 22 write · 1 server-management · **41 total**

See [Tool Reference](#tool-reference) below for per-tool descriptions.

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PRTG_HOST` | Yes | — | PRTG server URL (e.g., `https://prtg.example.com`) |
| `PRTG_API_KEY` | Yes | — | API key (create in PRTG: Setup > Account Settings > API Keys) |
| `PRTG_VERIFY_SSL` | No | `false` | Set `true` for CA-signed certs |
| `PRTG_READ_ONLY` | No | `true` | Set `false` to enable write operations |

### 3. Run

**Local:**
```bash
fastmcp run prtg-mcp.py
```

**Docker:**
```bash
docker build -t prtg-mcp .
docker run --env-file .env -p 8000:8000 prtg-mcp
```

### 4. Claude Code Integration

Add to your Claude Code MCP settings:

```json
{
  "mcpServers": {
    "prtg": {
      "command": "fastmcp",
      "args": ["run", "/path/to/prtg-mcp.py"]
    }
  }
}
```

---

## Tool Reference

### V2 Read Tools (14)

Always available regardless of `PRTG_READ_ONLY`.

| Tool | Description |
|------|-------------|
| `list_probes` | List probes with filtering/pagination/sorting |
| `list_groups` | List groups |
| `list_devices` | List devices |
| `get_device_templates` | Available device templates for auto-discovery |
| `list_sensors` | List sensors (most commonly used) |
| `list_channels` | List channels |
| `list_objects` | List objects across all types |
| `get_child_object_types` | Discover what can be created under an object |
| `get_timeseries` | Live or historic timeseries metric data |
| `list_users` | List users |
| `get_user` | Get user details |
| `list_user_groups` | List user groups |
| `get_user_group` | Get user group details |
| `get_license_info` | License information |

### V1 Read Tools (2)

| Tool | Description |
|------|-------------|
| `query_table` | Flexible table query — sensors, devices, messages, channels, tickets, reports, toplists, sysinfo |
| `get_historic_data` | Historic sensor data with date range and averaging interval |

### V1 Operational Tools (8) — requires `PRTG_READ_ONLY=false`

| Tool | Description |
|------|-------------|
| `pause_object` | Pause monitoring indefinitely with message |
| `pause_object_for` | Pause monitoring for N minutes |
| `resume_object` | Resume monitoring |
| `acknowledge_alarm` | Acknowledge down alert with message |
| `scan_now` | Force immediate sensor scan |
| `simulate_error` | Simulate error on sensor |
| `auto_discovery` | Run auto-discovery on group/device |
| `test_notification` | Test notification template |

### V1 Management Tools (7) — requires `PRTG_READ_ONLY=false`

| Tool | Description |
|------|-------------|
| `rename_object` | Rename any object |
| `set_object_property` | Change object properties |
| `set_priority` | Set priority (1-5) |
| `clone_object` | Clone group/device/sensor (starts paused) |
| `set_position` | Reorder in tree (up/down/top/bottom) |
| `set_geo_location` | Set geographic location |
| `add_to_report` | Add object to report |

### V2 Write Tools (7) — requires `PRTG_READ_ONLY=false`

| Tool | Description |
|------|-------------|
| `create_group` | Create group under probe/group |
| `create_device` | Create device |
| `create_sensor` | Create sensor on device |
| `update_sensor` | Update sensor properties |
| `move_object` | Move object in tree |
| `delete_object` | Delete object (cascading, irreversible) |
| `trigger_metascan` | Re-discover sensor types on device |

### Convenience Tools (2)

| Tool | Description |
|------|-------------|
| `get_problem_sensors` | List all non-Up sensors — "what's broken?" |
| `get_device_health` | Device sensor status summary (up/down/warn counts) |

### Server Tools (1)

| Tool | Description |
|------|-------------|
| `reload_prtg_impl` | Hot-reload the `prtg_impl` module so edits to existing functions take effect without restarting the MCP server. Adding brand-new tools still requires a full restart. |

---

## Safety

`PRTG_READ_ONLY` defaults to `true`. All 22 write tools return an error without contacting PRTG:

```
Write operations disabled. Set PRTG_READ_ONLY=false in .env to enable.
```

**Caution when write mode is enabled:**
- `delete_object` performs cascading, irreversible deletion — deleting a group removes all devices and sensors inside it
- `clone_object` creates objects in a paused state — remember to `resume_object` after cloning
- All write tools should be used carefully in production monitoring environments
