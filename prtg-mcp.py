from fastmcp import FastMCP
import requests
import urllib3
import json
import os
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
PRTG_API_KEY = os.getenv("PRTG_API_KEY", "")
PRTG_VERIFY_SSL = os.getenv("PRTG_VERIFY_SSL", "false").lower() == "true"
PRTG_READ_ONLY = os.getenv("PRTG_READ_ONLY", "true").lower() == "true"

if not PRTG_VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
    url = f"{PRTG_HOST}/api/v2{path}"
    headers = {
        "Authorization": f"Bearer {PRTG_API_KEY}",
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
    result = await _prtg_v2("GET", f"/experimental/objects/{parent_id}/types")
    return json.dumps(result, indent=2)


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


if __name__ == "__main__":
    mcp.run()
