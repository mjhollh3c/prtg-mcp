from fastmcp import FastMCP
import requests
import urllib3
import json
import os
import asyncio
from dotenv import load_dotenv
from typing import Optional

# Load environment variables
script_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(script_dir, ".env")
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
else:
    load_dotenv()

# Configuration
PRTG_HOST = os.getenv("PRTG_HOST", "").rstrip("/")
PRTG_V2_HOST = os.getenv("PRTG_V2_HOST", "").rstrip("/") or PRTG_HOST
PRTG_API_KEY = os.getenv("PRTG_API_KEY", "")
PRTG_USERNAME = os.getenv("PRTG_USERNAME", "")
PRTG_PASSWORD = os.getenv("PRTG_PASSWORD", "")
PRTG_VERIFY_SSL = os.getenv("PRTG_VERIFY_SSL", "false").lower() == "true"
PRTG_READ_ONLY = os.getenv("PRTG_READ_ONLY", "true").lower() == "true"

if not PRTG_VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# V2 session token management
_v2_token = None
_v2_token_lock = asyncio.Lock()


async def _get_v2_token() -> str:
    """Gets a V2 bearer token, obtaining one via session auth if needed."""
    global _v2_token
    async with _v2_token_lock:
        if _v2_token is not None:
            return _v2_token
        if PRTG_USERNAME and PRTG_PASSWORD:
            response = requests.post(
                f"{PRTG_V2_HOST}/api/v2/session",
                json={"username": PRTG_USERNAME, "password": PRTG_PASSWORD},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                verify=PRTG_VERIFY_SSL,
            )
            if response.status_code == 200 and "application/json" in response.headers.get("Content-Type", ""):
                token = response.json().get("token")
                if token:
                    _v2_token = token
                    return _v2_token
        if PRTG_API_KEY:
            _v2_token = PRTG_API_KEY
            return _v2_token
        raise Exception("No V2 auth available. Set PRTG_USERNAME/PRTG_PASSWORD or PRTG_API_KEY.")

# Create MCP server
mcp: FastMCP = FastMCP("PRTG Network Monitor MCP")


def _check_write_allowed() -> Optional[str]:
    """Returns error message if writes are disabled, None if allowed."""
    if PRTG_READ_ONLY:
        return "Write operations disabled. Set PRTG_READ_ONLY=false in .env to enable."
    return None


def _build_v2_list_params(
    filter: Optional[str] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    sort: Optional[str] = None,
    includes: Optional[str] = None,
) -> dict:
    """Builds query params dict for V2 list endpoints."""
    params = {}
    if filter:
        params["filter"] = filter
    if offset is not None:
        params["offset"] = offset
    if limit is not None:
        params["limit"] = limit
    else:
        params["limit"] = 500
    if sort:
        params["sort"] = sort
    if includes:
        params["includes"] = includes
    return params


async def _prtg_v2(
    method: str,
    path: str,
    params: Optional[dict] = None,
    json_body: Optional[dict] = None,
) -> dict:
    """Makes a request to PRTG API v2. Returns parsed JSON response."""
    global _v2_token
    token = await _get_v2_token()
    url = f"{PRTG_V2_HOST}/api/v2{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    response = requests.request(
        method=method,
        url=url,
        headers=headers,
        params=params,
        json=json_body,
        verify=PRTG_VERIFY_SSL,
    )
    if response.status_code == 401:
        # Token expired — invalidate and retry once
        async with _v2_token_lock:
            _v2_token = None
        token = await _get_v2_token()
        headers["Authorization"] = f"Bearer {token}"
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_body,
            verify=PRTG_VERIFY_SSL,
        )
    if response.status_code >= 400:
        raise Exception(
            f"PRTG API v2 error: {response.status_code} {response.reason} - {response.text}"
        )
    if response.status_code == 204 or not response.text:
        return {"status": "success", "code": response.status_code}
    return response.json()


async def _prtg_v1(
    endpoint: str,
    params: Optional[dict] = None,
    expect_json: bool = True,
) -> str:
    """Makes a request to PRTG API v1. Returns formatted JSON string or status message."""
    url = f"{PRTG_HOST}/api/{endpoint}"
    request_params = {"apitoken": PRTG_API_KEY}
    if params:
        request_params.update(params)
    response = requests.get(
        url=url,
        params=request_params,
        verify=PRTG_VERIFY_SSL,
    )
    if response.status_code >= 400:
        raise Exception(
            f"PRTG API v1 error: {response.status_code} {response.reason} - {response.text}"
        )
    if expect_json:
        return json.dumps(response.json(), indent=2)
    return f"Success (HTTP {response.status_code})"


# =============================================================================
# V2 READ TOOLS — Infrastructure Topology
# =============================================================================


@mcp.tool()
async def list_probes(
    filter: Optional[str] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    sort: Optional[str] = None,
    includes: Optional[str] = None,
) -> str:
    """List PRTG probes via the V2 API.

    Probes are the remote agents that execute monitoring checks on behalf of the
    PRTG core server. Each probe hosts one or more device groups and the sensors
    attached to them. Listing probes is useful for understanding the physical
    distribution of your monitoring infrastructure.

    Args:
        filter: OData-style filter expression. Examples:
            "name contains HQ" — probes whose name contains "HQ"
            "status eq Connected"
        offset: Zero-based index of the first record to return (for pagination).
        limit: Maximum number of records to return (default 500).
        sort: Field name to sort by, optionally prefixed with "-" for descending.
            Examples: "name", "-name"
        includes: Comma-separated list of additional related resources to embed.

    Returns:
        JSON string containing the list of probes and pagination metadata.
    """
    params = _build_v2_list_params(filter, offset, limit, sort, includes)
    result = await _prtg_v2("GET", "/experimental/probes", params=params)
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_groups(
    filter: Optional[str] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    sort: Optional[str] = None,
    includes: Optional[str] = None,
) -> str:
    """List PRTG device groups via the V2 API.

    Groups are organisational containers inside PRTG that hold devices (and
    other groups). They allow you to logically segment your monitored environment
    by location, function, customer, or any other taxonomy. Sensors inherit
    settings such as scanning intervals and credentials from their parent group.

    Args:
        filter: OData-style filter expression. Examples:
            "name contains Core" — groups whose name contains "Core"
            "status eq Down"
        offset: Zero-based index of the first record to return (for pagination).
        limit: Maximum number of records to return (default 500).
        sort: Field name to sort by, optionally prefixed with "-" for descending.
        includes: Comma-separated list of additional related resources to embed.

    Returns:
        JSON string containing the list of groups and pagination metadata.
    """
    params = _build_v2_list_params(filter, offset, limit, sort, includes)
    result = await _prtg_v2("GET", "/experimental/groups", params=params)
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_devices(
    filter: Optional[str] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    sort: Optional[str] = None,
    includes: Optional[str] = None,
) -> str:
    """List PRTG devices via the V2 API.

    Devices represent individual monitored hosts such as servers, routers,
    switches, firewalls, or any other network-addressable entity. Each device
    has an IP address or hostname and carries one or more sensors that perform
    the actual checks.

    Args:
        filter: OData-style filter expression. Examples:
            "name contains switch" — devices whose name contains "switch"
            "status eq Down"       — only devices currently in a Down state
            "host eq 192.168.1.1"  — device with a specific IP/hostname
        offset: Zero-based index of the first record to return (for pagination).
        limit: Maximum number of records to return (default 500).
        sort: Field name to sort by, optionally prefixed with "-" for descending.
            Examples: "name", "-host"
        includes: Comma-separated list of additional related resources to embed.

    Returns:
        JSON string containing the list of devices and pagination metadata.
    """
    params = _build_v2_list_params(filter, offset, limit, sort, includes)
    result = await _prtg_v2("GET", "/experimental/devices", params=params)
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_device_templates() -> str:
    """Return all available device templates from the PRTG V2 API.

    Device templates define a pre-configured set of sensors that PRTG can
    automatically apply to a newly added device. They are used during auto-
    discovery or manual device creation to quickly deploy a standard sensor
    profile suited to a particular device type (e.g. Cisco router, Windows
    server, VMware host).

    Returns:
        JSON string containing the list of device templates.
    """
    result = await _prtg_v2("GET", "/experimental/devices/templates")
    return json.dumps(result, indent=2)


# =============================================================================
# V2 READ TOOLS — Sensors & Channels
# =============================================================================


@mcp.tool()
async def list_sensors(
    filter: Optional[str] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    sort: Optional[str] = None,
    includes: Optional[str] = None,
) -> str:
    """List PRTG sensors via the V2 API.

    Sensors are the fundamental monitoring units in PRTG. Each sensor targets
    one specific aspect of a device — a ping check, an SNMP counter, a REST
    endpoint, a Windows service, etc. — and produces one or more channels of
    measurement data. Sensor status values are: Up, Down, Warning, Paused,
    Unknown.

    Args:
        filter: OData-style filter expression. Examples:
            "status eq Down"         — sensors that are currently Down
            "status eq Warning"      — sensors in Warning state
            "name contains ping"     — sensors whose name contains "ping"
            "parentId eq 2048"       — sensors belonging to device ID 2048
        offset: Zero-based index of the first record to return (for pagination).
        limit: Maximum number of records to return (default 500).
        sort: Field name to sort by, optionally prefixed with "-" for descending.
            Examples: "name", "-status"
        includes: Comma-separated list of additional related resources to embed.

    Returns:
        JSON string containing the list of sensors and pagination metadata.
    """
    params = _build_v2_list_params(filter, offset, limit, sort, includes)
    result = await _prtg_v2("GET", "/experimental/sensors", params=params)
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_channels(
    filter: Optional[str] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    sort: Optional[str] = None,
) -> str:
    """List PRTG channels via the V2 API.

    Channels are the individual measurement streams produced by a sensor. A
    single sensor can expose many channels — for example a traffic sensor may
    have separate channels for inbound traffic, outbound traffic, and errors.
    Channels store the numeric values, thresholds, and units that drive graphs
    and alerts.

    Args:
        filter: OData-style filter expression. Examples:
            "name contains Traffic"
            "parentId eq 1234"   — channels belonging to sensor ID 1234
        offset: Zero-based index of the first record to return (for pagination).
        limit: Maximum number of records to return (default 500).
        sort: Field name to sort by, optionally prefixed with "-" for descending.

    Returns:
        JSON string containing the list of channels and pagination metadata.
    """
    params = _build_v2_list_params(filter, offset, limit, sort, includes=None)
    result = await _prtg_v2("GET", "/experimental/channels", params=params)
    return json.dumps(result, indent=2)


# =============================================================================
# V2 READ TOOLS — Objects & Discovery
# =============================================================================


@mcp.tool()
async def list_objects(
    filter: Optional[str] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
    sort: Optional[str] = None,
    includes: Optional[str] = None,
) -> str:
    """List PRTG objects of all types via the V2 API.

    The objects endpoint is a unified view across every PRTG entity type —
    probes, groups, devices, and sensors — in a single collection. It is
    particularly useful for global searches or when you do not know in advance
    which object type contains the item you are looking for.

    Args:
        filter: OData-style filter expression. Examples:
            "name contains Core"
            "type eq Device"
            "status eq Down"
        offset: Zero-based index of the first record to return (for pagination).
        limit: Maximum number of records to return (default 500).
        sort: Field name to sort by, optionally prefixed with "-" for descending.
        includes: Comma-separated list of additional related resources to embed.

    Returns:
        JSON string containing the list of objects and pagination metadata.
    """
    params = _build_v2_list_params(filter, offset, limit, sort, includes)
    result = await _prtg_v2("GET", "/experimental/objects", params=params)
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_child_object_types(parent_id: int) -> str:
    """Return the child object types available under a given PRTG parent object.

    PRTG enforces a strict containment hierarchy: Core Server > Probe > Group >
    Device > Sensor. This endpoint tells you which child types are valid beneath
    a specific parent object, which is required knowledge before adding new
    objects programmatically.

    Args:
        parent_id: The numeric ID of the parent PRTG object whose allowed child
            types should be retrieved.

    Returns:
        JSON string listing the child object types available under the specified
        parent.
    """
    try:
        result = await _prtg_v2("GET", f"/experimental/objects/{parent_id}/types")
        return json.dumps(result, indent=2)
    except Exception:
        return json.dumps({"error": "This endpoint is not available on your PRTG version. Use get_device_templates instead for sensor type discovery."}, indent=2)


# =============================================================================
# V2 READ TOOLS — Timeseries Data
# =============================================================================


@mcp.tool()
async def get_timeseries(
    object_id: int,
    data_type: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> str:
    """Retrieve timeseries measurement data for a PRTG sensor or channel.

    PRTG records every sensor reading as a time-stamped data point. This
    endpoint exposes that historical or live measurement stream so you can
    analyse trends, investigate incidents, or build dashboards outside of the
    PRTG UI.

    Args:
        object_id: Numeric ID of the PRTG sensor or channel to query.
        data_type: The kind of data to retrieve. Must be one of:
            "historic" — averaged historical data stored in the PRTG database
            "live"     — the most recent real-time readings
        start: ISO-8601 datetime string for the beginning of the requested
            window. Example: "2025-01-01T00:00:00Z". Only applicable when
            data_type is "historic".
        end: ISO-8601 datetime string for the end of the requested window.
            Example: "2025-01-02T00:00:00Z". Only applicable when data_type
            is "historic".

    Returns:
        JSON string containing the timeseries data points.
    """
    params: dict = {}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    result = await _prtg_v2(
        "GET",
        f"/experimental/timeseries/{object_id}/{data_type}",
        params=params if params else None,
    )
    return json.dumps(result, indent=2)


# =============================================================================
# V2 READ TOOLS — Users & Access
# =============================================================================


@mcp.tool()
async def list_users(
    filter: Optional[str] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
) -> str:
    """List PRTG user accounts via the V2 API.

    PRTG maintains its own user directory. Each user account controls login
    credentials, notification delivery, and access rights to monitored objects.
    This endpoint is useful for auditing who has access to your PRTG instance.

    Args:
        filter: OData-style filter expression. Examples:
            "name contains john"
            "email contains example.com"
        offset: Zero-based index of the first record to return (for pagination).
        limit: Maximum number of records to return (default 500).

    Returns:
        JSON string containing the list of user accounts and pagination metadata.
    """
    params = _build_v2_list_params(filter, offset, limit, sort=None, includes=None)
    result = await _prtg_v2("GET", "/experimental/users", params=params)
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_user(user_id: int) -> str:
    """Retrieve a single PRTG user account by its numeric ID.

    Returns the full detail record for one user, including username, email
    address, group memberships, and permission settings.

    Args:
        user_id: The numeric ID of the PRTG user to retrieve.

    Returns:
        JSON string containing the user account details.
    """
    result = await _prtg_v2("GET", f"/experimental/users/{user_id}")
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_user_groups(
    filter: Optional[str] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
) -> str:
    """List PRTG user groups via the V2 API.

    User groups aggregate individual user accounts and allow administrators to
    assign object-level access rights to many users at once. A user can belong
    to multiple groups. This endpoint is useful for auditing role-based access
    control in your PRTG environment.

    Args:
        filter: OData-style filter expression. Examples:
            "name contains Admins"
            "name eq ReadOnly"
        offset: Zero-based index of the first record to return (for pagination).
        limit: Maximum number of records to return (default 500).

    Returns:
        JSON string containing the list of user groups and pagination metadata.
    """
    params = _build_v2_list_params(filter, offset, limit, sort=None, includes=None)
    result = await _prtg_v2("GET", "/experimental/usergroups", params=params)
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_user_group(group_id: int) -> str:
    """Retrieve a single PRTG user group by its numeric ID.

    Returns the full detail record for one user group, including its name,
    description, and the list of member user accounts.

    Args:
        group_id: The numeric ID of the PRTG user group to retrieve.

    Returns:
        JSON string containing the user group details.
    """
    result = await _prtg_v2("GET", f"/experimental/usergroups/{group_id}")
    return json.dumps(result, indent=2)


# =============================================================================
# V2 READ TOOLS — System
# =============================================================================


@mcp.tool()
async def get_license_info() -> str:
    """Retrieve PRTG license information via the V2 API.

    Returns details about the active PRTG license including the edition,
    maximum sensor count, expiry date, and current sensor usage. This is
    useful for capacity planning and ensuring the installation remains within
    its licensed limits.

    Returns:
        JSON string containing the PRTG license details.
    """
    result = await _prtg_v2("GET", "/experimental/license")
    return json.dumps(result, indent=2)


# =============================================================================
# V1 READ TOOLS — Table Queries & Historic Data
# =============================================================================


@mcp.tool()
async def query_table(
    content: str,
    columns: str,
    count: Optional[int] = None,
    start: Optional[int] = None,
    id: Optional[int] = None,
    filter_status: Optional[str] = None,
    filter_tags: Optional[str] = None,
    sort_by: Optional[str] = None,
) -> str:
    """Query any PRTG data table via the V1 API — the power tool for flexible data retrieval.

    The table.json endpoint is the most versatile read endpoint in the PRTG V1
    API. By choosing the right content type and columns you can retrieve sensors,
    devices, messages, channel values, tickets, reports, toplists, and system
    info all from a single call. It supports filtering by status or tag,
    sorting, and pagination.

    Args:
        content: The table type to query. One of:
            "sensors"       — all sensor objects
            "devices"       — all device objects
            "messages"      — log / message entries
            "channels"      — sensor channel data
            "values"        — raw measurement values
            "tickets"       — PRTG support tickets / TODOs
            "ticketdata"    — ticket detail rows
            "reports"       — scheduled report definitions
            "storedreports" — previously generated report files
            "toplists"      — top-N sensor lists
            "sysinfo"       — system-information tables
        columns: Comma-separated list of column names to include in the result.
            Common columns: "objid,device,sensor,status,lastvalue,message"
        count: Maximum number of rows to return. Defaults to 500, maximum 50000.
        start: Zero-based row index to start from (for pagination).
        id: Limit results to the subtree rooted at this PRTG object ID.
        filter_status: Filter by sensor status numeric code. Values:
            1=Unknown, 2=Collecting, 3=Up, 4=Warning, 5=Down, 6=NoProbe,
            7=PausedbyUser, 8=PausedbyDependency, 9=PausedbySchedule,
            10=Unusual, 11=PausedbyLicense, 12=PausedUntil,
            13=DownAcknowledged, 14=DownPartial
        filter_tags: Filter by tag expression, e.g. "@tag(bandwidth)".
        sort_by: Column to sort by. Prefix with "-" for descending order.

    Returns:
        JSON string containing the table rows and associated metadata.
    """
    params: dict = {
        "content": content,
        "columns": columns,
        "output": "json",
        "count": count if count is not None else 500,
    }
    if start is not None:
        params["start"] = start
    if id is not None:
        params["id"] = id
    if filter_status is not None:
        params["filter_status"] = filter_status
    if filter_tags is not None:
        params["filter_tags"] = filter_tags
    if sort_by is not None:
        params["sortby"] = sort_by
    return await _prtg_v1("table.json", params=params)


@mcp.tool()
async def get_historic_data(
    sensor_id: int,
    start_date: str,
    end_date: str,
    avg: Optional[int] = None,
) -> str:
    """Retrieve historic measurement data for a PRTG sensor via the V1 API.

    Returns averaged historic channel values for the specified sensor over the
    requested time window. Data is returned at the averaging interval specified
    by the avg parameter — shorter intervals produce more data points but cover
    less history. PRTG stores historic data for as long as the data retention
    policy allows.

    Args:
        sensor_id: The numeric ID of the sensor whose historic data to retrieve.
        start_date: Start of the time window in PRTG date format: YYYY-MM-DD-HH-MM-SS.
            Example: "2025-01-01-00-00-00"
        end_date: End of the time window in PRTG date format: YYYY-MM-DD-HH-MM-SS.
            Example: "2025-01-02-00-00-00"
        avg: Averaging interval in seconds. Common values: 60, 300, 3600, 86400.
            Defaults to 300 (5 minutes).

    Returns:
        JSON string containing the historic data rows, channel names, and units.
    """
    params: dict = {
        "id": sensor_id,
        "sdate": start_date,
        "edate": end_date,
        "usecaption": 1,
        "avg": avg if avg is not None else 300,
    }
    return await _prtg_v1("historicdata.json", params=params)


# =============================================================================
# V1 WRITE TOOLS — Operational Controls
# =============================================================================


@mcp.tool()
async def pause_object(
    object_id: int,
    message: Optional[str] = None,
) -> str:
    """Pause a PRTG object (sensor, device, group, or probe) indefinitely via the V1 API.

    Pausing stops all monitoring checks on the object and any sensors beneath it
    in the hierarchy. The object remains paused until it is explicitly resumed.
    Pausing is useful for planned maintenance windows or when you want to suppress
    alerts without deleting the monitoring configuration.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        object_id: The numeric ID of the PRTG object to pause.
        message: Optional human-readable reason for the pause, displayed in the
            PRTG UI and logs.

    Returns:
        Success message with HTTP status code, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    params: dict = {"id": object_id, "action": 0}
    if message is not None:
        params["pausemsg"] = message
    return await _prtg_v1("pause.htm", params=params, expect_json=False)


@mcp.tool()
async def pause_object_for(
    object_id: int,
    duration: int,
    message: Optional[str] = None,
) -> str:
    """Pause a PRTG object for a fixed duration, then automatically resume it.

    Unlike pause_object, this variant schedules an automatic resume after the
    specified number of minutes. This is ideal for short maintenance windows
    where you want monitoring to resume without manual intervention.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        object_id: The numeric ID of the PRTG object to pause.
        duration: Number of minutes to keep the object paused before auto-resume.
        message: Optional human-readable reason for the pause.

    Returns:
        Success message with HTTP status code, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    params: dict = {"id": object_id, "duration": duration}
    if message is not None:
        params["pausemsg"] = message
    return await _prtg_v1("pauseobjectfor.htm", params=params, expect_json=False)


@mcp.tool()
async def resume_object(object_id: int) -> str:
    """Resume a previously paused PRTG object via the V1 API.

    Resumes monitoring on a paused sensor, device, group, or probe. PRTG will
    immediately begin executing checks again and reporting results. Use this
    after a maintenance window or when an issue has been resolved.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        object_id: The numeric ID of the paused PRTG object to resume.

    Returns:
        Success message with HTTP status code, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    params: dict = {"id": object_id, "action": 1}
    return await _prtg_v1("pause.htm", params=params, expect_json=False)


@mcp.tool()
async def acknowledge_alarm(
    object_id: int,
    message: Optional[str] = None,
) -> str:
    """Acknowledge a PRTG alarm on a Down or DownAcknowledged sensor via the V1 API.

    Acknowledging an alarm signals that a human is aware of the problem and
    suppresses repeat notifications. The sensor continues to be monitored but
    its status changes to DownAcknowledged. The acknowledgement message is
    displayed in the PRTG UI and alarm history.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        object_id: The numeric ID of the PRTG sensor with an active alarm.
        message: Optional acknowledgement message explaining the situation or
            the action being taken.

    Returns:
        Success message with HTTP status code, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    params: dict = {"id": object_id}
    if message is not None:
        params["ackmsg"] = message
    return await _prtg_v1("acknowledgealarm.htm", params=params, expect_json=False)


@mcp.tool()
async def scan_now(object_id: int) -> str:
    """Force an immediate on-demand scan of a PRTG sensor or device via the V1 API.

    Triggers a single out-of-schedule check cycle on the specified object
    without waiting for the next regular scan interval. Useful for verifying
    that a resolved issue is actually fixed, or for getting an immediate reading
    after a configuration change.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        object_id: The numeric ID of the PRTG sensor or device to scan.

    Returns:
        Success message with HTTP status code, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    params: dict = {"id": object_id}
    return await _prtg_v1("scannow.htm", params=params, expect_json=False)


@mcp.tool()
async def simulate_error(object_id: int) -> str:
    """Simulate a sensor error on a PRTG sensor via the V1 API.

    Forces the specified sensor into a Down state, which is useful for testing
    alert and notification pipelines without waiting for a real failure. The
    simulated error will be cleared on the next regular scan cycle.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        object_id: The numeric ID of the PRTG sensor to put into a simulated
            error state.

    Returns:
        Success message with HTTP status code, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    params: dict = {"id": object_id, "action": 1}
    return await _prtg_v1("simulate.htm", params=params, expect_json=False)


@mcp.tool()
async def auto_discovery(
    object_id: int,
    template: Optional[str] = None,
) -> str:
    """Trigger an auto-discovery scan on a PRTG group or device via the V1 API.

    Auto-discovery scans the network segment associated with the target object
    and automatically adds newly found devices and sensors based on the specified
    device template. Useful for keeping your monitoring tree up to date as
    infrastructure changes.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        object_id: The numeric ID of the PRTG group or device to run discovery on.
        template: Optional name of a device template to apply to discovered
            devices. If omitted, PRTG uses its default auto-discovery templates.

    Returns:
        Success message with HTTP status code, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    params: dict = {"id": object_id}
    if template is not None:
        params["template"] = template
    return await _prtg_v1("discovernow.htm", params=params, expect_json=False)


@mcp.tool()
async def test_notification(notification_id: int) -> str:
    """Send a test notification via a PRTG notification contact via the V1 API.

    Triggers a test delivery through the specified notification contact (email,
    SMS, webhook, etc.) so you can verify that the delivery channel is correctly
    configured without waiting for a real alert.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        notification_id: The numeric ID of the PRTG notification contact to test.

    Returns:
        Success message with HTTP status code, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    params: dict = {"id": notification_id}
    return await _prtg_v1("notificationtest.htm", params=params, expect_json=False)


# =============================================================================
# V1 WRITE TOOLS — Object Management
# =============================================================================


@mcp.tool()
async def rename_object(object_id: int, new_name: str) -> str:
    """Rename a PRTG object (sensor, device, group, or probe) via the V1 API.

    Changes the display name of the specified object in the PRTG UI. The rename
    is immediate and does not affect monitoring behaviour or collected data.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        object_id: The numeric ID of the PRTG object to rename.
        new_name: The new display name to assign to the object.

    Returns:
        Success message with HTTP status code, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    params: dict = {"id": object_id, "value": new_name}
    return await _prtg_v1("rename.htm", params=params, expect_json=False)


@mcp.tool()
async def set_object_property(
    object_id: int,
    name: str,
    value: str,
) -> str:
    """Set an arbitrary property on a PRTG object via the V1 API.

    Writes a single named property value to any PRTG object. This is the
    general-purpose setter used to change settings such as scanning intervals,
    credentials, thresholds, and other sensor-specific or device-specific
    parameters. Consult the PRTG documentation for valid property names for each
    object type.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        object_id: The numeric ID of the PRTG object to modify.
        name: The internal property name to set (e.g. "interval", "host",
            "tags", "priority").
        value: The new value for the property as a string.

    Returns:
        Success message with HTTP status code, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    params: dict = {"id": object_id, "name": name, "value": value}
    return await _prtg_v1("setobjectproperty.htm", params=params, expect_json=False)


@mcp.tool()
async def set_priority(object_id: int, priority: int) -> str:
    """Set the priority star-rating of a PRTG object via the V1 API.

    PRTG allows each object to be assigned a priority from 1 (lowest) to 5
    (highest). Priority affects the display order in certain views and can be
    used to focus attention on the most critical sensors or devices.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        object_id: The numeric ID of the PRTG object whose priority to change.
        priority: Priority level, an integer from 1 (lowest) to 5 (highest).

    Returns:
        Success message with HTTP status code, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    params: dict = {"id": object_id, "prio": priority}
    return await _prtg_v1("setpriority.htm", params=params, expect_json=False)


@mcp.tool()
async def clone_object(
    object_id: int,
    name: str,
    target_id: Optional[int] = None,
    host: Optional[str] = None,
) -> str:
    """Clone (duplicate) a PRTG object into the same or a different parent via the V1 API.

    Creates a copy of the specified sensor, device, or group with all its
    settings and child objects. The cloned object is placed under target_id if
    provided, or under the same parent as the original if not.

    IMPORTANT: Cloned objects always start in a PAUSED state. You must
    explicitly resume them (via resume_object) after cloning and making any
    desired configuration adjustments.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        object_id: The numeric ID of the PRTG object to clone.
        name: Display name for the newly cloned object.
        target_id: Optional numeric ID of the parent object under which to
            place the clone. If omitted, PRTG places it under the original's
            parent.
        host: Optional hostname or IP address for the cloned device. Only
            applicable when cloning a device object.

    Returns:
        Success message with HTTP status code, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    params: dict = {"id": object_id, "name": name}
    if target_id is not None:
        params["targetid"] = target_id
    if host is not None:
        params["host"] = host
    return await _prtg_v1("duplicateobject.htm", params=params, expect_json=False)


@mcp.tool()
async def set_position(object_id: int, position: str) -> str:
    """Change the display position of a PRTG object within its parent container.

    Adjusts where the object appears in the PRTG UI relative to its siblings.
    Useful for keeping frequently monitored or critical objects at the top of
    lists for quicker access.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        object_id: The numeric ID of the PRTG object to reposition.
        position: Direction or absolute position. Must be one of:
            "up"     — move one position up in the list
            "down"   — move one position down in the list
            "top"    — move to the very top of the list
            "bottom" — move to the very bottom of the list

    Returns:
        Success message with HTTP status code, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    params: dict = {"id": object_id, "newpos": position}
    return await _prtg_v1("setposition.htm", params=params, expect_json=False)


@mcp.tool()
async def set_geo_location(
    object_id: int,
    location: str,
    lonlat: str,
) -> str:
    """Set the geographic location of a PRTG object via the V1 API.

    Associates a human-readable location label and GPS coordinates with a
    PRTG device or group. These values are displayed on PRTG map widgets and
    geographic dashboards.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        object_id: The numeric ID of the PRTG object to geolocate.
        location: Human-readable location description, e.g. "New York, NY, USA".
        lonlat: GPS coordinates as a "longitude,latitude" string,
            e.g. "-74.006,40.7128".

    Returns:
        Success message with HTTP status code, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    params: dict = {"id": object_id, "location": location, "lonlat": lonlat}
    return await _prtg_v1("setlonlat.htm", params=params, expect_json=False)


@mcp.tool()
async def add_to_report(report_id: int, object_id: int) -> str:
    """Add a sensor to a PRTG report via the V1 API.

    Associates a sensor with an existing scheduled or on-demand report so that
    the sensor's data is included the next time the report is generated. Reports
    can aggregate data from many sensors into a single PDF or HTML document.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        report_id: The numeric ID of the PRTG report to add the sensor to.
        object_id: The numeric ID of the PRTG sensor to include in the report.

    Returns:
        Success message with HTTP status code, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    params: dict = {"id": report_id, "addid": object_id}
    return await _prtg_v1("reportaddsensor.htm", params=params, expect_json=False)


# =============================================================================
# V2 WRITE TOOLS — Create, Update, Move, Delete
# =============================================================================


@mcp.tool()
async def create_group(parent_id: int, parent_type: str, name: str) -> str:
    """Create a new group under a probe or group via the V2 API.

    Groups are the organisational containers used to arrange devices inside a
    probe or inside another group. Use this tool to build out the hierarchy of
    your PRTG monitoring tree.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        parent_id: Numeric ID of the parent probe or group that will contain
            the new group.
        parent_type: The type of the parent object. Must be either "probes"
            or "groups".
        name: Display name for the new group.

    Returns:
        JSON string with the created group object, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    result = await _prtg_v2(
        "POST",
        f"/experimental/{parent_type}/{parent_id}/group",
        json_body={"basic": {"name": name}},
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def create_device(
    parent_id: int, parent_type: str, name: str, host: str
) -> str:
    """Create a new device under a group or probe via the V2 API.

    Devices represent the physical or virtual hosts that PRTG monitors. A device
    must belong to either a group or a probe and must have a resolvable hostname
    or IP address so that sensors can reach it.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        parent_id: Numeric ID of the parent group or probe.
        parent_type: Type of the parent object. Typically "groups" or "probes".
        name: Display name for the new device.
        host: Hostname or IP address that PRTG will use to contact the device.

    Returns:
        JSON string with the created device object, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    result = await _prtg_v2(
        "POST",
        f"/experimental/{parent_type}/{parent_id}/device",
        json_body={"basic": {"name": name, "host": host}},
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def create_sensor(
    device_id: int,
    sensor_type: str,
    name: str,
    properties: Optional[str] = None,
) -> str:
    """Create a new sensor on a device via the V2 API.

    Sensors perform the actual monitoring checks (ping, SNMP, HTTP, etc.). Each
    sensor belongs to exactly one device and executes according to its own
    scanning interval and inherited channel settings.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        device_id: Numeric ID of the device that will host the new sensor.
        sensor_type: Sensor type identifier string as recognised by PRTG,
            e.g. "ping", "snmpcustom", "http".
        name: Display name for the new sensor.
        properties: Optional JSON string of additional sensor properties to
            merge into the creation payload, e.g. '{"interval": 60}'.

    Returns:
        JSON string with the created sensor object, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    body: dict = {"name": name, "type": sensor_type}
    if properties:
        body.update(json.loads(properties))
    result = await _prtg_v2(
        "POST",
        f"/experimental/devices/{device_id}/sensor",
        json_body=body,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def update_sensor(sensor_id: int, properties: str) -> str:
    """Update properties of an existing sensor via the V2 API.

    Patches one or more sensor attributes without replacing the whole object.
    Only the keys present in the properties JSON are modified; all other
    sensor settings remain unchanged.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        sensor_id: Numeric ID of the sensor to update.
        properties: JSON string of the properties to change, e.g.
            '{"name": "New Name", "interval": 300}'.

    Returns:
        JSON string with the updated sensor object, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    result = await _prtg_v2(
        "PATCH",
        f"/experimental/sensor/{sensor_id}",
        json_body=json.loads(properties),
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def move_object(
    object_id: int, object_type: str, target_id: int
) -> str:
    """Move a PRTG object to a different parent container via the V2 API.

    Relocates a probe, group, device, or sensor to a new parent without
    disrupting its configuration or historical data. Useful for reorganising
    the monitoring hierarchy after infrastructure changes.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        object_id: Numeric ID of the object to move.
        object_type: Type of the object to move. One of "probes", "groups",
            "devices", or "sensors".
        target_id: Numeric ID of the destination parent object.

    Returns:
        JSON string with the result of the move operation, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    result = await _prtg_v2(
        "POST",
        f"/experimental/{object_type}/{object_id}/move",
        json_body={"parent": str(target_id)},
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def delete_object(object_id: int, object_type: str) -> str:
    """Delete a PRTG object permanently via the V2 API.

    WARNING: This is a cascading delete and cannot be undone. Deleting a group
    will also delete all devices and sensors within it. Deleting a device will
    delete all its sensors. All associated historical data will be lost.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        object_id: Numeric ID of the object to delete.
        object_type: Type of the object to delete. One of "probes", "groups",
            "devices", or "sensors".

    Returns:
        JSON string with the result of the delete operation, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    result = await _prtg_v2(
        "DELETE",
        f"/experimental/{object_type}/{object_id}",
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def trigger_metascan(device_id: int) -> str:
    """Trigger an auto-discovery metascan on a device via the V2 API.

    A metascan instructs PRTG to probe the target device and automatically
    suggest or create sensors based on the services and protocols it discovers.
    This is equivalent to running "Add Sensor (Auto-Discovery)" in the PRTG web
    interface.

    Note: Write operations must be enabled (PRTG_READ_ONLY=false in .env).

    Args:
        device_id: Numeric ID of the device to scan.

    Returns:
        JSON string with the metascan result, or an error string.
    """
    err = _check_write_allowed()
    if err:
        return err
    result = await _prtg_v2(
        "POST",
        f"/experimental/devices/{device_id}/metascan",
    )
    return json.dumps(result, indent=2)


# =============================================================================
# CONVENIENCE TOOLS — Composite Read-Only
# =============================================================================


@mcp.tool()
async def get_problem_sensors(limit: Optional[int] = None) -> str:
    """Return all sensors that are not in the 'Up' state via the V2 API.

    A pre-built "what's broken?" query that filters the sensor list to only
    those with a status other than Up. This includes sensors that are Down,
    Warning, Unusual, Paused, or in any other non-healthy state. Use this as
    a quick health check across the entire monitoring environment.

    Args:
        limit: Maximum number of problem sensors to return. Defaults to 500
            when not specified.

    Returns:
        JSON string containing the list of non-Up sensors and pagination
        metadata.
    """
    params = _build_v2_list_params(
        filter="status in [DOWN,WARNING,UNKNOWN,UNUSUAL,COLLECTING,NONE]",
        limit=limit,
    )
    result = await _prtg_v2("GET", "/experimental/sensors", params=params)
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_device_health(device_id: int) -> str:
    """Return a sensor status summary for a single device via the V1 API.

    Retrieves a compact overview of how many sensors on the specified device
    are Up, Down, Down (acknowledged), Partially Down, Warning, Paused,
    Unusual, or Undefined. Use this to quickly assess the overall health of a
    device without listing every individual sensor.

    Args:
        device_id: Numeric ID of the PRTG device to summarise.

    Returns:
        JSON string containing the device row with all sensor-count columns.
    """
    params = {
        "content": "devices",
        "columns": "objid,name,host,upsens,downsens,downacksens,partialdownsens,warnsens,pausedsens,unusualsens,undefinedsens,totalsens",
        "id": device_id,
        "count": 1,
        "output": "json",
    }
    return await _prtg_v1("table.json", params=params)


if __name__ == "__main__":
    mcp.run()
