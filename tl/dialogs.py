from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from .constants import APP_NAME


class SettingsDialog(QDialog):
    def __init__(
        self, parent: QWidget, start_minimized: bool, minimize_to_tray: bool
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")

        layout = QVBoxLayout(self)

        self.start_minimized_checkbox = QCheckBox("Start minimized", self)
        self.start_minimized_checkbox.setChecked(start_minimized)
        layout.addWidget(self.start_minimized_checkbox)

        self.minimize_to_tray_checkbox = QCheckBox("Minimize to tray", self)
        self.minimize_to_tray_checkbox.setChecked(minimize_to_tray)
        layout.addWidget(self.minimize_to_tray_checkbox)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, self
        )
        layout.addWidget(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)


def prompt_for_openai_api_key(parent: QWidget) -> Optional[str]:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Connect your OpenAI account")

    layout = QVBoxLayout(dialog)
    copy = (
        "Connect your OpenAI account\n"
        "Your API key stays on your device and is used only for your requests.\n"
        "You control usage and billing."
    )
    lbl = QLabel(copy, dialog)
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.PlainText)
    layout.addWidget(lbl)

    link = QLabel(
        '<a href="https://platform.openai.com/api-keys">https://platform.openai.com/api-keys</a>',
        dialog,
    )
    link.setOpenExternalLinks(True)
    layout.addWidget(link)

    api_key_input = QLineEdit(dialog)
    api_key_input.setPlaceholderText("sk-...")
    api_key_input.setEchoMode(QLineEdit.Password)
    layout.addWidget(api_key_input)

    buttons = QDialogButtonBox(
        QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, dialog
    )
    layout.addWidget(buttons)

    def accept_if_present() -> None:
        key = api_key_input.text().strip()
        if key:
            dialog.done(QDialog.Accepted)
        else:
            api_key_input.setFocus()

    buttons.accepted.connect(accept_if_present)
    buttons.rejected.connect(dialog.reject)

    api_key_input.setFocus()

    result = dialog.exec()
    if result == QDialog.Accepted:
        return api_key_input.text().strip()
    return None


def show_about(parent: QWidget, base_dir: Path, app_name: str = APP_NAME) -> None:
    QMessageBox.information(
        parent,
        "About tl",
        f"{app_name}\n\n"
        "- PySide6 translator UI\n"
        "- Backend: OpenAI (extensible)\n"
        "- Data stored in AppDataLocation:\n"
        f"  {base_dir}\n",
    )
