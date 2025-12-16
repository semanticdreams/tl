import json
import os
from dataclasses import asdict
from typing import Dict, List

from .models import TranslationRecord


class Persistence:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
        self.settings_path = os.path.join(self.base_dir, "settings.json")
        self.history_path = os.path.join(self.base_dir, "history.jsonl")

    def load_settings(self) -> Dict:
        if not os.path.exists(self.settings_path):
            return {}
        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_settings(self, settings: Dict) -> None:
        tmp = self.settings_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.settings_path)

    def append_history(self, rec: TranslationRecord) -> None:
        line = json.dumps(asdict(rec), ensure_ascii=False)
        with open(self.history_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def read_history_lines(self) -> List[str]:
        if not os.path.exists(self.history_path):
            return []
        with open(self.history_path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
