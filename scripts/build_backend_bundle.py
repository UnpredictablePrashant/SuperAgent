#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = ROOT / "electron-app" / ".bundled-backend"
DEFAULT_NAME = "kendr-backend"

COLLECT_SUBMODULES = (
    "kendr",
    "tasks",
    "mcp_servers",
    "plugin_templates",
)

COLLECT_DATA = (
    "kendr",
    "tasks",
    "mcp_servers",
    "plugin_templates",
)

COPY_METADATA = (
    "openai",
    "langchain",
    "langchain-core",
    "langchain-openai",
    "langgraph",
    "fastmcp",
    "browser-use",
    "requests",
    "beautifulsoup4",
    "pypdf",
    "python-docx",
    "sqlalchemy",
    "chromadb",
    "rich",
)

EXTRA_DATA = (
    ("project_templates", "project_templates"),
    ("docs", "docs"),
    (".env.example", ".env.example"),
)


def _data_arg(src: Path, dest: str) -> str:
    return f"{src}{os.pathsep}{dest}"


def build_bundle(output_dir: Path, *, name: str, clean: bool) -> Path:
    output_dir = output_dir.resolve()
    bundle_dir = output_dir / name
    work_dir = ROOT / "build" / "pyinstaller" / name
    spec_dir = ROOT / "build" / "pyinstaller-spec"

    if clean:
        shutil.rmtree(bundle_dir, ignore_errors=True)
        shutil.rmtree(work_dir, ignore_errors=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)

    args: list[str] = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--console",
        "--name",
        name,
        "--distpath",
        str(output_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(spec_dir),
        "--paths",
        str(ROOT),
    ]

    for package_name in COLLECT_SUBMODULES:
        args.extend(["--collect-submodules", package_name])
    for package_name in COLLECT_DATA:
        args.extend(["--collect-data", package_name])
    for dist_name in COPY_METADATA:
        args.extend(["--copy-metadata", dist_name])
    for src_name, dest_name in EXTRA_DATA:
        src_path = ROOT / src_name
        if src_path.exists():
            args.extend(["--add-data", _data_arg(src_path, dest_name)])

    args.append(str(ROOT / "gateway_server.py"))

    print(f"[bundle] building {name} into {bundle_dir}")
    subprocess.run(args, cwd=ROOT, check=True)
    return bundle_dir


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a standalone Kendr backend bundle for Electron packaging."
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory that will contain the onedir backend bundle.",
    )
    parser.add_argument(
        "--name",
        default=DEFAULT_NAME,
        help="Bundle/executable name (default: kendr-backend).",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Reuse previous PyInstaller work/dist directories when possible.",
    )
    args = parser.parse_args()

    bundle_dir = build_bundle(
        Path(args.output_dir),
        name=args.name,
        clean=not args.no_clean,
    )
    print(f"[bundle] ready: {bundle_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
