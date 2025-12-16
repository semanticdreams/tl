from typing import List, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox


class LanguageComboBox(QComboBox):
    changed = Signal()

    def __init__(self, items: List[Tuple[str, str]], allow_auto: bool, parent=None):
        super().__init__(parent)
        self.setEditable(False)
        self.setInsertPolicy(QComboBox.NoInsert)
        self._allow_auto = allow_auto

        for code, name in items:
            if (code == "auto") and (not allow_auto):
                continue
            self.addItem(f"{name} ({code})", code)

        self.currentIndexChanged.connect(lambda _: self.changed.emit())

    def current_lang_code(self) -> str:
        code = self.currentData(Qt.UserRole)
        return code or ("auto" if self._allow_auto else "en")

    def set_lang_code(self, code: str) -> None:
        desired = code or ("auto" if self._allow_auto else "en")
        idx = self.findData(desired, role=Qt.UserRole)
        if idx >= 0:
            self.setCurrentIndex(idx)
            return
        if self.count() > 0:
            self.setCurrentIndex(0)
