"""Command-line interface for report generation."""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Sequence

from .config import AppConfig
from .logging_utils import setup_logger
from .reports import generate_all_reports


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="org-timeviz",
        description="Generate time tracking reports from Org CLOCK entries.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/default.yaml"),
        help="Path to YAML config file.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run report generation and return a process exit code."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    config_path = args.config.expanduser().resolve()
    cfg = AppConfig.from_yaml(config_path)

    setup_logger(level=cfg.app.log_level)
    logging.getLogger(__name__).info("Loaded config from %s", config_path)

    generate_all_reports(cfg)
    return os.EX_OK
