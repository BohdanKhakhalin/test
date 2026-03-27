"""CLI for Posmat AI action automation."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Tuple

from posmat_ai_automation.common.api_client import (
    PosmatAPIClient,
    create_api_research_config,
)
from posmat_ai_automation.common.data_writer import CSVResultWriter
from posmat_ai_automation.evaluations.ai_actions.config import PosmatAIActionConfig
from posmat_ai_automation.evaluations.ai_actions.data_loader import PosmatActionDataLoader
from posmat_ai_automation.evaluations.ai_actions.evaluator import PosmatAIActionEvaluator
from posmat_ai_automation.evaluations.ai_actions.models import OUTPUT_COLUMNS

LOGGER = logging.getLogger("posmat_ai_actions")
DEFAULT_WORKERS = 10


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Posmat AI actions from a CSV file.")
    parser.add_argument("--input", help="Path to the input CSV file.")
    parser.add_argument("--output-dir", help="Directory for output CSV files.")
    parser.add_argument("--workers", type=int, help="Number of worker threads.")
    parser.add_argument("--timeout", type=int, help="Per-request timeout in seconds.")
    parser.add_argument("--bot-content", help="Path to botContent JSON.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build requests without sending them.",
    )
    return parser.parse_args()


def resolve_paths(
    project_root: Path,
    args: argparse.Namespace,
    config: PosmatAIActionConfig,
) -> Tuple[Path, Path, Path]:
    input_path = Path(args.input) if args.input else project_root / "input_data" / "input.csv"
    output_dir = Path(args.output_dir) if args.output_dir else project_root / "output_data"
    bot_content_path = Path(args.bot_content) if args.bot_content else Path(config.bot_content_path)

    if not input_path.is_absolute():
        input_path = project_root / input_path
    if not output_dir.is_absolute():
        output_dir = project_root / output_dir
    if not bot_content_path.is_absolute():
        bot_content_path = project_root / bot_content_path

    return input_path, output_dir, bot_content_path


def main() -> int:
    configure_logging()
    args = parse_args()
    project_root = Path(__file__).resolve().parents[2]

    try:
        config = PosmatAIActionConfig(env_path=project_root / ".env")
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("step=load_env_failed error=%s", exc)
        return 1

    input_path, output_dir, bot_content_path = resolve_paths(project_root, args, config)
    if not input_path.exists():
        LOGGER.error("step=input_missing path=%s", input_path)
        return 1
    if not bot_content_path.exists():
        LOGGER.error("step=bot_content_missing path=%s", bot_content_path)
        return 1

    timeout = args.timeout if args.timeout is not None else config.request_timeout
    workers = args.workers if args.workers is not None else DEFAULT_WORKERS

    data_loader = PosmatActionDataLoader()
    bot_content = data_loader.load_bot_content_json(bot_content_path)
    attribute_catalog = data_loader.get_attribute_catalog(bot_content)
    test_inputs = data_loader.load_from_csv(input_path)

    api_config = create_api_research_config(config.base_url, config.bot_public_id)
    api_client = PosmatAPIClient(api_config, config.api_token)
    evaluator = PosmatAIActionEvaluator(
        api_client=api_client,
        attribute_catalog=attribute_catalog,
        updatable_attribute_types=api_config.updatable_attribute_types,
    )

    results = evaluator.run(
        test_inputs,
        workers=workers,
        timeout=timeout,
        dry_run=bool(args.dry_run),
    )

    writer = CSVResultWriter(
        filename_prefix="run_posmat_ai_actions",
        output_dir=str(output_dir),
    )
    output_path = writer.save_results(
        [result.to_dict() for result in results],
        columns=OUTPUT_COLUMNS,
    )
    LOGGER.info("step=completed output=%s rows=%s", output_path, len(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
