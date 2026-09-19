#!/usr/bin/env python3
"""
Helper to initialize RTK in this project.
Usage: python scripts/rtk/setup_rtk.py --generator copilot
This script checks for the `rtk` CLI and runs `rtk init -g <generator>`.
If `rtk` is not found, it prints install instructions (see https://github.com/rtk-ai/rtk).
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def find_rtk():
    return shutil.which("rtk")


def run_rtk_init(generator: str):
    rtk_cmd = find_rtk()
    # If rtk not found in PATH, try local .tools/rtk
    if not rtk_cmd:
        local = Path('.tools/rtk/rtk')
        if local.exists():
            rtk_cmd = str(local)
        else:
            local_win = Path('.tools/rtk/rtk.exe')
            if local_win.exists():
                rtk_cmd = str(local_win)
    if not rtk_cmd:
        print("RTK CLI not found in PATH.")
        print("Please install RTK following https://github.com/rtk-ai/rtk and ensure `rtk` is on your PATH.")
        print("Common install (if Python/pip based):")
        print("  pip install rtk")
        print("Or follow the project's Quick Start for your environment.")
        return 2

    cmd = [rtk_cmd, "init", "-g", generator]
    print(f"Running: {' '.join(cmd)} in {Path.cwd()}\n")
    try:
        proc = subprocess.run(cmd, check=False)
        return proc.returncode
    except Exception as e:
        print(f"Failed to run RTK: {e}")
        return 3


def main():
    parser = argparse.ArgumentParser(description="Run rtk init for this repository")
    parser.add_argument("--generator", "-g", default="copilot", help="Generator name to pass to rtk (default: copilot)")
    args = parser.parse_args()

    rc = run_rtk_init(args.generator)
    if rc == 0:
        print("RTK init completed successfully.")
    else:
        print(f"RTK init exited with code {rc}.")
    sys.exit(rc)


if __name__ == "__main__":
    main()
