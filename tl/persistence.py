import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List

from .models import TranslationRecord


class Persistence:
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.base_dir / "settings.json"
        self.history_path = self.base_dir / "history.jsonl"

    def load_settings(self) -> Dict:
        if not self.settings_path.exists():
            return {}
        try:
            with self.settings_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_settings(self, settings: Dict) -> None:
        tmp = self.settings_path.with_suffix(self.settings_path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        tmp.replace(self.settings_path)

    def append_history(self, rec: TranslationRecord) -> None:
        line = json.dumps(asdict(rec), ensure_ascii=False)
        with self.history_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def read_history_lines(self) -> List[str]:
        if not self.history_path.exists():
            return []
        with self.history_path.open("r", encoding="utf-8") as f:
            return f.read().splitlines()

    def clear_history(self) -> None:
        if not self.history_path.exists():
            return
        try:
            self.history_path.unlink()
        except OSError:
            # If removal fails (e.g., permission issues), fall back to truncation.
            with self.history_path.open("w", encoding="utf-8") as f:
                f.truncate(0)
