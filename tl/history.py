from typing import List

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItemModel, QStandardItem

from .models import TranslationRecord


class HistoryListModel(QStandardItemModel):
    def __init__(self, parent=None):
        super().__init__(parent)

    @staticmethod
    def format_item(rec: TranslationRecord) -> str:
        src = rec.source_text.replace("\n", " ").strip()
        preview = (src[:100] + "…") if len(src) > 100 else src
        return f"[{rec.source_lang}->{rec.target_lang}] {preview}"

    def add_records(self, records: List[TranslationRecord]) -> None:
        for rec in records:
            item = QStandardItem(self.format_item(rec))
            item.setEditable(False)
            item.setData(rec, Qt.UserRole)
            self.appendRow(item)
