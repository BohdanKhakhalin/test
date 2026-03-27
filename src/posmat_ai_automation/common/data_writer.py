"""Shared CSV result writer."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd


class CSVResultWriter:
    """Write timestamped CSV result files."""

    def __init__(
        self,
        filename_prefix: str = "results",
        output_dir: str = "output_data",
        timestamp_format: str = "%Y%m%d_%H%M%S",
    ) -> None:
        self.filename_prefix = filename_prefix
        self.output_dir = Path(output_dir)
        self.timestamp_format = timestamp_format

    def save_results(
        self,
        records: List[Dict[str, Any]],
        *,
        columns: Optional[Iterable[str]] = None,
    ) -> Path:
        if not records:
            raise ValueError("Cannot save empty results list")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime(self.timestamp_format)
        output_path = self.output_dir / f"{self.filename_prefix}_{timestamp}.csv"

        dataframe = pd.DataFrame(records)
        if columns is not None:
            dataframe = dataframe.reindex(columns=list(columns))
        dataframe.to_csv(output_path, index=False)
        return output_path
