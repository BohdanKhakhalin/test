"""CSV and bot-content loaders for Posmat AI action runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping

import pandas as pd

from posmat_ai_automation.evaluations.ai_actions.models import PosmatActionInput


class PosmatActionDataLoader:
    """Load input CSV rows and bot content metadata."""

    def load_from_csv(self, csv_path: Path) -> List[PosmatActionInput]:
        try:
            dataframe = pd.read_csv(
                csv_path,
                dtype=str,
                keep_default_na=False,
                skip_blank_lines=False,
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"Input CSV not found: {csv_path}") from exc

        rows = dataframe.to_dict(orient="records")
        return [
            PosmatActionInput(
                row_index=index,
                row_data={str(key): value for key, value in row.items()},
            )
            for index, row in enumerate(rows, start=1)
        ]

    def load_bot_content_json(self, path: Path) -> Dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def get_attribute_catalog(
        self,
        bot_content: Mapping[str, Any],
    ) -> Dict[str, Dict[str, str]]:
        catalog: Dict[str, Dict[str, str]] = {}
        for item in bot_content.get("attributes", []):
            name = str(item.get("name", "")).strip()
            if name:
                catalog[name] = {
                    "type": str(item.get("type", "")).strip(),
                    "description": str(item.get("description", "")).strip(),
                }
        return catalog
