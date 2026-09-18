"""Small command-line entry point for environment diagnostics."""

from __future__ import annotations

import argparse
import platform
import sys

from roco_ebbo import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="roco-ebbo")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="print environment information for a bug report")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "doctor":
        print(f"roco-ebbo={__version__}")
        print(f"python={sys.version.split()[0]}")
        print(f"platform={platform.platform()}")
        print("status=scaffold-ready; RoCo implementation begins in Stage 2")
