"""CSV loader for Posmat AI action runs."""

from __future__ import annotations

from pathlib import Path
from typing import List

import pandas as pd

from posmat_ai_automation.evaluations.ai_actions.models import PosmatActionInput


class PosmatActionDataLoader:
    """Load input CSV rows."""

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

        if "input" not in dataframe.columns:
            raise ValueError("Input CSV must contain an 'input' column")

        rows = dataframe.to_dict(orient="records")
        return [
            PosmatActionInput(
                row_index=index,
                row_data={str(key): value for key, value in row.items()},
            )
            for index, row in enumerate(rows, start=1)
        ]
