# PRTG Network Monitor MCP Server

A Model Context Protocol (MCP) server that exposes 40 tools for interacting with a PRTG Network Monitor installation. The server wraps both the modern PRTG REST API v2 and the classic v1 query-string API, giving AI assistants full read and (optionally) write access to your monitoring environment.

---

## Setup

### 1. Install dependencies

```bash
pip install fastmcp requests python-dotenv
```

### 2. Configure environment

Copy or create a `.env` file in the same directory as `prtg-mcp.py`:

```env
PRTG_HOST=https://your-prtg-server.example.com
PRTG_API_KEY=your-api-token-here
PRTG_VERIFY_SSL=false
PRTG_READ_ONLY=true
```

### 3. Run locally

```bash
fastmcp run prtg-mcp.py
```

### 4. Run with Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY prtg-mcp.py .env ./
RUN pip install fastmcp requests python-dotenv
CMD ["fastmcp", "run", "prtg-mcp.py"]
```

```bash
docker build -t prtg-mcp .
docker run --rm prtg-mcp
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `PRTG_HOST` | Yes | _(empty)_ | Base URL of your PRTG server, e.g. `https://prtg.example.com`. No trailing slash. |
| `PRTG_API_KEY` | Yes | _(empty)_ | PRTG API token (found in PRTG under Setup → My Account → API Token). |
| `PRTG_VERIFY_SSL` | No | `false` | Set to `true` to verify the PRTG server's TLS certificate. Set to `false` for self-signed certs. |
| `PRTG_READ_ONLY` | No | `true` | When `true`, all write operations are blocked and return an error. Set to `false` to enable create, update, move, delete, and other mutating tools. |

---

## Claude Code MCP Configuration

Add the following to your Claude Code MCP configuration (typically `~/.claude/claude_desktop_config.json` or the workspace `.mcp.json`):

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

Replace `/path/to/prtg-mcp.py` with the absolute path to the script on your system.

---

## Tool Reference

### V2 Read Tools (14 tools)

These tools use the PRTG REST API v2 with Bearer token authentication. They are always available regardless of `PRTG_READ_ONLY`.

| Tool | Description |
|---|---|
| `list_probes` | List all PRTG probes with optional filtering, sorting, and pagination. |
| `get_probe` | Get full details for a single probe by ID. |
| `list_groups` | List all device groups with optional filtering, sorting, and pagination. |
| `get_group` | Get full details for a single group by ID. |
| `list_devices` | List all devices with optional filtering, sorting, and pagination. |
| `get_device` | Get full details for a single device by ID. |
| `list_sensors` | List all sensors with optional filtering, sorting, and pagination. |
| `get_sensor` | Get full details for a single sensor by ID. |
| `list_channels` | List all channels for a given sensor. |
| `get_channel` | Get full details for a single channel by sensor ID and channel ID. |
| `list_objects` | List PRTG objects of any type using the generic objects endpoint. |
| `list_timeseries` | Query timeseries data for a sensor channel over a time range. |
| `list_users` | List all PRTG user accounts. |
| `get_license` | Retrieve current PRTG license information. |

### V1 Read Tools (2 tools)

These tools use the classic PRTG v1 API with API token authentication.

| Tool | Description |
|---|---|
| `query_table` | Query any PRTG table (sensors, devices, groups, etc.) with custom column selection and filtering. |
| `get_historic_data` | Retrieve historic sensor channel data for a specified time range. |

### V1 Operational Tools (8 tools)

Write-gated. These tools perform operational actions on PRTG objects.

| Tool | Description |
|---|---|
| `pause_object` | Pause monitoring for a PRTG object with an optional message and duration. |
| `resume_object` | Resume monitoring for a paused PRTG object. |
| `acknowledge_alarm` | Acknowledge a down sensor alarm with a message and optional duration. |
| `scan_now` | Trigger an immediate scan on a sensor or device. |
| `simulate_alarm` | Simulate an alarm state on a sensor (for testing). |
| `start_autodiscovery` | Start auto-discovery on a group or device to find new sensors. |
| `test_notification` | Send a test notification via a PRTG notification contact. |
| `mark_ticket_completed` | Mark a PRTG status ticket as completed. |

### V1 Management Tools (7 tools)

Write-gated. These tools modify PRTG object properties and configuration.

| Tool | Description |
|---|---|
| `rename_object` | Rename any PRTG object. |
| `set_object_property` | Set a single named property on any PRTG object. |
| `set_priority` | Set the priority (star rating 1–5) of a PRTG object. |
| `clone_object` | Clone an existing PRTG object to a new parent. |
| `set_position` | Set the display position of an object within its parent container. |
| `set_geo_location` | Set the geographic location and GPS coordinates of an object. |
| `add_to_report` | Add a sensor to an existing PRTG report. |

### V2 Write Tools (7 tools)

Write-gated. These tools use the PRTG REST API v2 to create, modify, move, and delete objects.

| Tool | Description |
|---|---|
| `create_group` | Create a new group under a probe or group. |
| `create_device` | Create a new device under a group or probe with a hostname or IP. |
| `create_sensor` | Create a new sensor on a device with optional extra properties. |
| `update_sensor` | Patch one or more properties of an existing sensor. |
| `move_object` | Move any object to a different parent container. |
| `delete_object` | Permanently delete an object and all its children (cascading, irreversible). |
| `trigger_metascan` | Trigger an auto-discovery metascan on a device. |

### Convenience Tools (2 tools)

Read-only composite tools for common queries.

| Tool | Description |
|---|---|
| `get_problem_sensors` | Return all sensors that are not in the Up state — a quick "what's broken?" view. |
| `get_device_health` | Return a sensor status summary (up/down/warn counts) for a single device. |

---

## Safety

`PRTG_READ_ONLY` defaults to `true`. In this mode all write-gated tools return an error immediately without contacting the PRTG server:

```
Write operations disabled. Set PRTG_READ_ONLY=false in .env to enable.
```

Before enabling write mode, note that:

- **`delete_object`** performs a **cascading, irreversible delete**. Deleting a group removes all devices and sensors inside it, along with all their historical data.
- **`create_sensor`** and **`trigger_metascan`** can generate significant network traffic if run against many devices simultaneously.
- All write tools should be used with care in production monitoring environments.

Set `PRTG_READ_ONLY=false` only when you need to make changes, and consider reverting to `true` afterwards.
