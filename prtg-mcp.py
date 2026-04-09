"""PRTG MCP server — thin FastMCP wrapper around prtg_impl.

All business logic lives in ``prtg_impl``. This file only:

1. Creates the FastMCP instance.
2. Auto-registers every public async function from prtg_impl as a tool,
   using a dynamic-dispatch wrapper so that ``importlib.reload(prtg_impl)``
   actually takes effect without restarting the MCP server.
3. Exposes ``reload_prtg_impl`` as a tool so edits to prtg_impl.py can be
   loaded in-place from within Claude Code.

Why the dynamic wrapper? FastMCP captures the callable passed to
``@mcp.tool()`` at registration time, so naively calling
``importlib.reload(prtg_impl)`` would leave the old function references
alive. The wrapper here looks up ``getattr(prtg_impl, name)`` on every
invocation, which means reload is honoured.

Signatures, docstrings, and type annotations are copied from the real
implementation functions via ``functools.wraps`` so FastMCP still generates
correct JSON schemas for each tool.
"""

from __future__ import annotations

import functools
import importlib
import inspect

from fastmcp import FastMCP

import prtg_impl

mcp: FastMCP = FastMCP("PRTG Network Monitor MCP")


def _make_tool_wrapper(name: str):
    """Build a tool wrapper that re-resolves the target on every call.

    functools.wraps copies ``__wrapped__``, ``__doc__``, ``__name__``, and
    ``__annotations__`` from the current implementation so FastMCP generates
    the right schema. Inside the wrapper we use ``getattr`` at call time so
    reloaded versions take effect.
    """
    target = getattr(prtg_impl, name)

    @functools.wraps(target)
    async def wrapper(*args, **kwargs):
        return await getattr(prtg_impl, name)(*args, **kwargs)

    # Preserve the signature explicitly (belt and suspenders — some
    # versions of inspect.signature walk __wrapped__ but others read
    # __signature__ directly).
    wrapper.__signature__ = inspect.signature(target)
    return wrapper


def _register_all_tools() -> list[str]:
    """Register every public async function from prtg_impl as an MCP tool."""
    registered: list[str] = []
    for name, fn in inspect.getmembers(prtg_impl, inspect.iscoroutinefunction):
        if name.startswith("_"):
            continue
        if fn.__module__ != prtg_impl.__name__:
            # Skip anything pulled in via ``from ... import`` (e.g.
            # asyncio.* helpers) so we only expose our own tools.
            continue
        mcp.tool()(_make_tool_wrapper(name))
        registered.append(name)
    return registered


_REGISTERED_TOOLS = _register_all_tools()


@mcp.tool()
async def reload_prtg_impl() -> str:
    """Hot-reload the ``prtg_impl`` module so edits take effect without
    restarting the MCP server or Claude Code.

    Reloads the implementation module in place. Existing tool wrappers use
    dynamic dispatch, so subsequent tool calls will run the updated code.

    NOTE: Reloading only picks up changes to existing functions and helpers.
    Adding a brand-new tool still requires an MCP server restart because
    tools are registered during startup.

    Returns:
        A short status line listing how many tools are wired up and
        confirming the reload completed.
    """
    importlib.reload(prtg_impl)
    return (
        f"prtg_impl reloaded successfully. "
        f"{len(_REGISTERED_TOOLS)} implementation tools available; "
        f"new tools (if any) require an MCP restart."
    )


if __name__ == "__main__":
    mcp.run()
