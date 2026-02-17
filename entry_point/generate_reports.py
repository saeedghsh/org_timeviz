from __future__ import annotations

import argparse
import logging
from pathlib import Path

from org_timeviz.config import AppConfig
from org_timeviz.logging_utils import setup_logger
from org_timeviz.reports import generate_all_reports


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m entry_point.generate_reports",
        description="Generate time tracking reports from Org CLOCK entries.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/default.yaml"),
        help="Path to YAML config file.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    config_path = args.config.expanduser().resolve()

    cfg = AppConfig.from_yaml(config_path)

    setup_logger(level=cfg.app.log_level)
    logging.getLogger(__name__).info("Loaded config from %s", config_path)

    generate_all_reports(cfg)


if __name__ == "__main__":
    main()
