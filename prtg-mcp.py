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


if __name__ == "__main__":
    mcp.run()
