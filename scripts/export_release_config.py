#!/usr/bin/env python3
"""Export the active local ArcReel configuration as a private dotenv bundle."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        help="SQLite database path. Defaults to ArcReel's configured database.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".env.release"),
        help="Output dotenv file (default: .env.release).",
    )
    return parser.parse_args()


async def _export(output: Path) -> None:
    from lib.config_bundle import export_release_config_bundle, write_config_bundle_env
    from lib.db import async_session_factory, close_db

    try:
        async with async_session_factory() as session:
            bundle = await export_release_config_bundle(session)
        write_config_bundle_env(output.resolve(), bundle)
    finally:
        await close_db()


def main() -> None:
    args = _parse_args()
    if args.database is not None:
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{args.database.resolve()}"
    asyncio.run(_export(args.output))
    print(f"Exported private configuration bundle to {args.output.resolve()}")


if __name__ == "__main__":
    main()
