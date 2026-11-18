"""kite-ai CLI and systemd socket-activated IPC handler."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from . import DEFAULT_MAX_INPUT_TOKENS
from .abstractions import EnvSecretStore, SystemClock, UrllibHttpClient
from .index.store import IndexStore
from .models import ProviderConfig, TokenBudget
from .privacy import PrivacyFilter
from .providers.router import QueryRouter
from .tools.os_tools import OsToolbox


def default_db_path() -> Path:
    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        return Path(xdg_data) / "kite-ai" / "index.db"
    return Path.home() / ".local" / "share" / "kite-ai" / "index.db"


def handle_ipc_request(
    line: str,
    *,
    store: IndexStore,
    router: QueryRouter,
    toolbox: OsToolbox,
) -> dict[str, object]:
    """Handle one newline-delimited JSON IPC request from kite-aid.socket."""
    req = json.loads(line)
    op = str(req.get("op", "query"))
    if op == "query":
        resp = router.query(str(req.get("q", "")), force_cloud=bool(req.get("force_cloud", False)))
        return {"ok": True, "result": asdict(resp)}
    if op == "status":
        return {"ok": True, "result": asdict(store.telemetry())}
    if op == "tool":
        tool = str(req.get("tool", ""))
        args = req.get("args") or {}
        if tool == "search_local_index":
            res = toolbox.search_local_index(str(args.get("query", "")), limit=int(args.get("limit", 10)))
        elif tool == "inspect_file_head":
            res = toolbox.inspect_file_head(str(args.get("abs_path", "")))
        elif tool == "apply_os_setting":
            res = toolbox.apply_os_setting(args)
        elif tool == "diagnose_runtime":
            res = toolbox.diagnose_runtime(str(args.get("runtime", "all")))
        else:
            return {"ok": False, "error": f"Unknown tool: {tool}"}
        return {"ok": res.ok, "result": asdict(res)}
    return {"ok": False, "error": f"Unknown IPC operation: {op}"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kite-ai", description="KITE_OS Zero-Idle-RAM AI & Local Data Miner")
    p.add_argument("--db", type=Path, default=default_db_path(), help="SQLite FTS5 database path")
    p.add_argument("--hw-profile", type=Path, default=Path("/run/kite-os/hw-profile.json"))
    p.add_argument("--kiteignore", type=Path, default=None)
    p.add_argument("--json", action="store_true", dest="json_output", help="Emit JSON output")

    sub = p.add_subparsers(dest="command", required=True)

    p_idx = sub.add_parser("index", help="Incrementally index directories into SQLite FTS5")
    p_idx.add_argument("paths", nargs="+", type=Path)
    p_idx.add_argument("--force", action="store_true")

    p_q = sub.add_parser("query", help="Run Tier 0 local or Tier 1 compressed BYOK query")
    p_q.add_argument("text")
    p_q.add_argument("--provider", default="offline", choices=("offline", "gemini", "openai", "anthropic", "groq", "openrouter"))
    p_q.add_argument("--model", default="gemini-2.5-flash")
    p_q.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_INPUT_TOKENS)
    p_q.add_argument("--force-cloud", action="store_true")

    p_tool = sub.add_parser("tool", help="Invoke a sandboxed OS tool")
    p_tool.add_argument("name", choices=("search_local_index", "inspect_file_head", "apply_os_setting", "diagnose_runtime"))
    p_tool.add_argument("--arg", default="{}", help="JSON object arguments")

    sub.add_parser("status", help="Show SQLite FTS5 index telemetry")
    sub.add_parser("ipc-once", help="Process one JSON IPC request from stdin")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    privacy = PrivacyFilter(kiteignore_path=args.kiteignore)

    with IndexStore(args.db, privacy=privacy) as store:
        if args.command == "index":
            totals = {"indexed": 0, "skipped_unchanged": 0, "blocked_privacy": 0}
            for target in args.paths:
                res = store.index_directory(target, force=args.force)
                for k in totals:
                    totals[k] += res[k]
            print(json.dumps({"ok": True, "stats": totals}, indent=2))
            return 0

        if args.command == "status":
            print(json.dumps({"ok": True, "telemetry": asdict(store.telemetry())}, indent=2))
            return 0

        if args.command == "query":
            cfg = ProviderConfig(
                provider=args.provider,
                model=args.model,
                token_budget=TokenBudget(max_input_tokens=args.max_tokens),
            )
            router = QueryRouter(
                store,
                secret_store=EnvSecretStore(),
                http_client=UrllibHttpClient(),
                clock=SystemClock(),
                config=cfg,
                hw_profile_path=args.hw_profile,
            )
            resp = router.query(args.text, force_cloud=args.force_cloud)
            print(json.dumps(asdict(resp), indent=2))
            return 0

        toolbox = OsToolbox(store, hw_profile_path=args.hw_profile, privacy=privacy)
        if args.command == "tool":
            payload = json.loads(args.arg)
            out = handle_ipc_request(
                json.dumps({"op": "tool", "tool": args.name, "args": payload}),
                store=store,
                router=QueryRouter(
                    store,
                    secret_store=EnvSecretStore(),
                    http_client=UrllibHttpClient(),
                    clock=SystemClock(),
                    hw_profile_path=args.hw_profile,
                ),
                toolbox=toolbox,
            )
            print(json.dumps(out, indent=2))
            return 0 if out.get("ok") else 1

        if args.command == "ipc-once":
            line = sys.stdin.readline()
            router = QueryRouter(
                store,
                secret_store=EnvSecretStore(),
                http_client=UrllibHttpClient(),
                clock=SystemClock(),
                hw_profile_path=args.hw_profile,
            )
            out = handle_ipc_request(line, store=store, router=router, toolbox=toolbox)
            print(json.dumps(out))
            return 0 if out.get("ok") else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
