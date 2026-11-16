"""Environment self-check for the packaged HyperMesh meshing MCP.

Default run is read-only: imports the server, counts tools, resolves paths.
`--full` additionally runs a real hmbatch connectivity probe, which takes a
license token for a few seconds.

Usage:
    .venv\\Scripts\\python.exe verify_env.py
    .venv\\Scripts\\python.exe verify_env.py --full
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    print(f"[1/4] project root : {ROOT}")
    try:
        import hypermesh_mcp_server as server
    except Exception as exc:  # noqa: BLE001
        print(f"      FAIL import: {type(exc).__name__}: {exc}")
        print("      -> check that 'mcp<2' is installed (see requirements.lock.txt)")
        return 1
    print("      OK  import hypermesh_mcp_server")

    try:
        tools = server.mcp._tool_manager.list_tools()  # noqa: SLF001
        print(f"[2/4] tool count  : {len(tools)}")
    except Exception as exc:  # noqa: BLE001
        print(f"      WARN unable to enumerate tools: {exc}")

    located = server.locate_hypermesh()
    print("[3/4] executables :")
    print(json.dumps(located, ensure_ascii=False, indent=2))
    if not located.get("selected"):
        print("      -> set HYPERMESH_BATCH_EXE or edit hypermesh_batch_path.txt")
        return 1

    if "--full" not in sys.argv:
        print("[4/4] connectivity: SKIPPED (pass --full to run a real hmbatch probe)")
        return 0

    print("[4/4] connectivity: running hmbatch probe (consumes a license briefly)...")
    result = server.check_hypermesh_connection()
    print(json.dumps(result, ensure_ascii=False, indent=2)[:1200])
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
