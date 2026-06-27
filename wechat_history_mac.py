#!/usr/bin/env python3
"""
macOS wrapper for WeChat 4.x history extraction.

This project keeps the user's WeChat data, extracted keys, decrypted databases,
and exports out of git. It delegates low-level SQLCipher key scanning and
database decryption to ylytdeng/wechat-decrypt, then exposes a smaller workflow
for this machine.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent
TOOLS_DIR = ROOT / "tools" / "wechat-decrypt"
VENV_DIR = TOOLS_DIR / ".venv"
UPSTREAM_REPO = "https://github.com/ylytdeng/wechat-decrypt.git"
WECHAT_APP = Path("/Applications/WeChat.app")
WECHAT_CONTAINER = (
    Path.home()
    / "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"
)
BUNDLED_PYTHON = Path(
    "/Users/mxz/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
)


def run(cmd: list[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    print("+ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=str(cwd or ROOT), check=check)


def capture(cmd: list[str], cwd: Optional[Path] = None) -> str:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd or ROOT),
            check=False,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError:
        return ""
    return ((result.stdout or "") + (result.stderr or "")).strip()


def usable_python(path: str | Path) -> bool:
    result = subprocess.run(
        [str(path), "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def find_python() -> str:
    env_py = os.environ.get("WECHAT_HISTORY_PYTHON")
    candidates: list[str | Path] = []
    if env_py:
        candidates.append(env_py)
    candidates.extend(
        [
            sys.executable,
            "python3.12",
            "python3.11",
            "python3.10",
            BUNDLED_PYTHON,
            "python3",
        ]
    )
    for candidate in candidates:
        resolved = shutil.which(str(candidate)) or str(candidate)
        if Path(resolved).exists() or shutil.which(str(candidate)):
            if usable_python(resolved):
                return resolved
    raise SystemExit("No Python 3.10+ found. Set WECHAT_HISTORY_PYTHON=/path/to/python3.")


def venv_python() -> Path:
    return VENV_DIR / "bin" / "python3"


def detect_db_dirs() -> list[Path]:
    if not WECHAT_CONTAINER.exists():
        return []
    dirs = [
        p
        for p in WECHAT_CONTAINER.glob("*/db_storage")
        if p.is_dir() and (p / "message/message_0.db").exists()
    ]
    return sorted(dirs, key=lambda p: p.stat().st_mtime, reverse=True)


def selected_db_dir() -> Path:
    env_dir = os.environ.get("WECHAT_DB_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    dirs = detect_db_dirs()
    if not dirs:
        raise SystemExit(
            "No WeChat db_storage directory found. Set WECHAT_DB_DIR manually."
        )
    return dirs[0]


def wechat_version() -> str:
    if not WECHAT_APP.exists():
        return "not installed"
    out = capture(["plutil", "-extract", "CFBundleShortVersionString", "raw", str(WECHAT_APP / "Contents/Info.plist")])
    return out or "unknown"


def wechat_signature_flags() -> str:
    if not WECHAT_APP.exists():
        return ""
    out = capture(["codesign", "-dv", str(WECHAT_APP)])
    for line in out.splitlines():
        if "flags=" in line:
            return line.strip()
    return ""


def sqlite_status(db_path: Path) -> str:
    if not db_path.exists():
        return "missing"
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("select name from sqlite_master limit 1").fetchall()
        conn.close()
        return "plain sqlite"
    except sqlite3.DatabaseError:
        return "encrypted or non-sqlite"


def ensure_tools() -> None:
    if TOOLS_DIR.exists():
        return
    TOOLS_DIR.parent.mkdir(parents=True, exist_ok=True)
    git = shutil.which("git")
    if not git:
        raise SystemExit("git is required to install tools.")
    run([git, "clone", "--depth", "1", UPSTREAM_REPO, str(TOOLS_DIR)])


def write_config() -> Path:
    ensure_tools()
    db_dir = selected_db_dir()
    cfg = {
        "db_dir": str(db_dir),
        "keys_file": "all_keys.json",
        "decrypted_dir": "decrypted",
        "wechat_process": "WeChat",
    }
    config_path = TOOLS_DIR / "config.json"
    config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {config_path}")
    return config_path


def install_minimal_deps() -> None:
    ensure_tools()
    py = find_python()
    if not venv_python().exists():
        run([py, "-m", "venv", str(VENV_DIR)])
    run([str(venv_python()), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(venv_python()), "-m", "pip", "install", "pycryptodome>=3.19,<4", "zstandard>=0.22,<1", "flask>=3,<4", "requests>=2,<3"])


def compile_scanner() -> None:
    ensure_tools()
    scanner = TOOLS_DIR / "find_all_keys_macos"
    source = TOOLS_DIR / "find_all_keys_macos.c"
    run(["cc", "-O2", "-o", str(scanner), str(source), "-framework", "Foundation"], cwd=TOOLS_DIR)
    run(["codesign", "-s", "-", str(scanner)], cwd=TOOLS_DIR, check=False)


def install_tools(args: argparse.Namespace) -> None:
    ensure_tools()
    write_config()
    install_minimal_deps()
    compile_scanner()
    if args.full:
        run([str(venv_python()), "-m", "pip", "install", "-r", "requirements.txt"], cwd=TOOLS_DIR)


def doctor(_: argparse.Namespace) -> None:
    db_dirs = detect_db_dirs()
    db_dir = db_dirs[0] if db_dirs else None
    key_info = WECHAT_CONTAINER / "all_users/login"

    print("Environment")
    print(f"  macOS: {capture(['sw_vers', '-productVersion']) or 'unknown'}")
    print(f"  arch: {platform.machine()}")
    print(f"  WeChat: {wechat_version()} at {WECHAT_APP if WECHAT_APP.exists() else 'missing'}")
    print(f"  signature: {wechat_signature_flags() or 'unknown'}")
    print(f"  Python 3.10+: {find_python()}")
    print(f"  cc: {shutil.which('cc') or 'missing'}")
    print()
    print("WeChat data")
    print(f"  container: {WECHAT_CONTAINER}")
    print(f"  db_storage candidates: {len(db_dirs)}")
    for candidate in db_dirs[:5]:
        print(f"    - {candidate}")
    if db_dir:
        print(f"  selected db_dir: {db_dir}")
        for rel in ("message/message_0.db", "contact/contact.db", "session/session.db"):
            print(f"  {rel}: {sqlite_status(db_dir / rel)}")
    print(f"  key_info roots: {key_info if key_info.exists() else 'missing'}")
    print()
    print("Tooling")
    print(f"  tools dir: {TOOLS_DIR if TOOLS_DIR.exists() else 'not installed'}")
    print(f"  venv: {venv_python() if venv_python().exists() else 'not created'}")
    print(f"  scanner: {(TOOLS_DIR / 'find_all_keys_macos') if (TOOLS_DIR / 'find_all_keys_macos').exists() else 'not compiled'}")
    print(f"  config: {(TOOLS_DIR / 'config.json') if (TOOLS_DIR / 'config.json').exists() else 'missing'}")
    print(f"  keys: {(TOOLS_DIR / 'all_keys.json') if (TOOLS_DIR / 'all_keys.json').exists() else 'missing'}")
    print(f"  decrypted: {(TOOLS_DIR / 'decrypted') if (TOOLS_DIR / 'decrypted').exists() else 'missing'}")
    print()
    if "runtime" in wechat_signature_flags():
        print("Next blocking step")
        print("  WeChat is hardened-signed. Before key scanning, quit WeChat and run:")
        print("  sudo codesign --force --deep --sign - /Applications/WeChat.app")
        print("  Then reopen WeChat, log in, open a few chats, and run decrypt.")


def require_tools_ready() -> None:
    if not TOOLS_DIR.exists():
        raise SystemExit("Tools are not installed. Run: python wechat_history_mac.py install-tools")
    if not venv_python().exists():
        raise SystemExit("Virtualenv is missing. Run: python wechat_history_mac.py install-tools")


def decrypt(_: argparse.Namespace) -> None:
    require_tools_ready()
    write_config()
    scanner = TOOLS_DIR / "find_all_keys_macos"
    if not scanner.exists():
        compile_scanner()
    if "runtime" in wechat_signature_flags():
        raise SystemExit(
            "WeChat still has Hardened Runtime. Quit WeChat, run:\n"
            "  sudo codesign --force --deep --sign - /Applications/WeChat.app\n"
            "Then reopen WeChat and rerun decrypt."
        )
    run(["sudo", str(scanner)], cwd=TOOLS_DIR)
    run([str(venv_python()), "decrypt_db.py"], cwd=TOOLS_DIR)


def serve(_: argparse.Namespace) -> None:
    require_tools_ready()
    run([str(venv_python()), "monitor_web.py"], cwd=TOOLS_DIR)


def export(args: argparse.Namespace) -> None:
    require_tools_ready()
    cmd = [str(venv_python()), "export_all_chats.py"]
    if args.output:
        cmd.append(args.output)
    run(cmd, cwd=TOOLS_DIR)


def main() -> None:
    parser = argparse.ArgumentParser(description="macOS WeChat history workflow")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check local WeChat, data paths, and tooling").set_defaults(func=doctor)

    install_parser = sub.add_parser("install-tools", help="clone upstream tools, create venv, and compile scanner")
    install_parser.add_argument("--full", action="store_true", help="install upstream optional dependencies too")
    install_parser.set_defaults(func=install_tools)

    sub.add_parser("write-config", help="write tools/wechat-decrypt/config.json").set_defaults(func=lambda _: write_config())
    sub.add_parser("compile-scanner", help="compile macOS key scanner").set_defaults(func=lambda _: compile_scanner())
    sub.add_parser("decrypt", help="scan keys and decrypt WeChat databases").set_defaults(func=decrypt)
    sub.add_parser("serve", help="start upstream local web UI").set_defaults(func=serve)

    export_parser = sub.add_parser("export", help="export chats with upstream exporter")
    export_parser.add_argument("output", nargs="?", help="optional output directory")
    export_parser.set_defaults(func=export)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
