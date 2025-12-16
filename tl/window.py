from __future__ import annotations

import json
import time
from contextlib import contextmanager
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, QThread, QCoreApplication, QModelIndex
from PySide6.QtGui import QAction, QIcon, QStandardItem
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QLabel,
    QListView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStatusBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
)

import keyring

from .backends import BACKENDS
from .constants import APP_NAME, DEBOUNCE_MS, HISTORY_CHUNK, OPENAI_TRANSLATION_MODEL
from .history import HistoryListModel
from .languages import LANGUAGES
from .models import TranslateJob, TranslationRecord
from .persistence import Persistence
from .resources import load_icon
from .worker import TranslatorWorker
from .widgets import LanguageComboBox


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setObjectName(APP_NAME)
        self.app_icon: QIcon = load_icon()
        self.setWindowIcon(self.app_icon)

        self.base_dir = QCoreApplication.applicationDirPath()
        self.store = Persistence(self.base_dir)

        self.current_backend = "OpenAI"
        self._ui_enabled = True
        self._ui_disabled_reason: Optional[str] = None
        self._suppress_schedule = False

        # Translation scheduling/coalescing
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._maybe_start_translation)

        self._in_flight = False
        self._pending_job: Optional[TranslateJob] = None
        self._active_job: Optional[TranslateJob] = None
        self._latest_job: Optional[TranslateJob] = None  # last requested intent

        # History
        self._history_lines: List[str] = []
        self._history_loaded = 0  # how many items loaded into list model (from newest)
        self.history_model = HistoryListModel(self)

        self._build_ui()
        self._build_tray()
        self._load_settings()
        self.set_backend(self.current_backend, prompt_if_missing=True, schedule=False)
        self._load_history_initial()

        self._update_status()

    # UI ------------------------------------------------------------------

    def _build_ui(self):
        self.setStatusBar(QStatusBar(self))
        self.status_label = QLabel("Idle")
        self.statusBar().addPermanentWidget(self.status_label)

        mb = self.menuBar()

        file_menu = mb.addMenu("&File")
        self.act_show_hide = QAction("Hide", self)
        self.act_show_hide.triggered.connect(self.toggle_visible)
        file_menu.addAction(self.act_show_hide)

        file_menu.addSeparator()
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.quit_app)
        file_menu.addAction(act_quit)

        backend_menu = mb.addMenu("&Backend")
        self.backend_actions: Dict[str, QAction] = {}

        def add_backend_action(name: str, enabled: bool):
            act = QAction(name, self)
            act.setCheckable(True)
            act.setEnabled(enabled)
            act.triggered.connect(lambda _=False, n=name: self.set_backend(n))
            backend_menu.addAction(act)
            self.backend_actions[name] = act

        add_backend_action("OpenAI", True)
        add_backend_action("DeepL (coming soon)", False)
        add_backend_action("Google Translate (coming soon)", False)
        self.backend_actions["OpenAI"].setChecked(True)

        about_menu = mb.addMenu("&About")
        act_about = QAction("About tl", self)
        act_about.triggered.connect(self.show_about)
        about_menu.addAction(act_about)

        root = QWidget(self)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 8)

        splitter = QSplitter(Qt.Horizontal, root)

        # Main pane
        main_pane = QWidget(splitter)
        main_layout = QHBoxLayout(main_pane)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)

        self.src_lang = LanguageComboBox(LANGUAGES, allow_auto=True)
        self.tgt_lang = LanguageComboBox(LANGUAGES, allow_auto=False)

        self.src_text = QPlainTextEdit()
        self.tgt_text = QPlainTextEdit()
        self.tgt_text.setReadOnly(False)  # allow editing if user wants; translation overwrites

        # source pane
        src_pane = QWidget()
        src_layout = QVBoxLayout(src_pane)
        src_layout.setContentsMargins(0, 0, 0, 0)
        src_layout.setSpacing(6)
        src_layout.addWidget(self.src_lang)
        src_layout.addWidget(self.src_text)

        # target pane
        tgt_pane = QWidget()
        tgt_layout = QVBoxLayout(tgt_pane)
        tgt_layout.setContentsMargins(0, 0, 0, 0)
        tgt_layout.setSpacing(6)
        tgt_layout.addWidget(self.tgt_lang)
        tgt_layout.addWidget(self.tgt_text)

        swap_wrap = QWidget()
        swap_layout = QVBoxLayout(swap_wrap)
        swap_layout.setContentsMargins(0, 0, 0, 0)
        swap_layout.addStretch(1)
        self.swap_btn = QPushButton("⇄")
        self.swap_btn.setFixedWidth(44)
        self.swap_btn.clicked.connect(self.swap_languages_and_text)
        swap_layout.addWidget(self.swap_btn, alignment=Qt.AlignHCenter)
        swap_layout.addStretch(2)

        main_layout.addWidget(src_pane, stretch=1)
        main_layout.addWidget(swap_wrap, stretch=0)
        main_layout.addWidget(tgt_pane, stretch=1)

        # Sidebar: history list view
        sidebar = QWidget(splitter)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(6)

        side_layout.addWidget(QLabel("History"))
        self.history_view = QListView()
        self.history_view.setModel(self.history_model)
        self.history_view.clicked.connect(self.on_history_clicked)
        side_layout.addWidget(self.history_view, 1)

        self.clear_history_btn = QPushButton("Clear History")
        self.clear_history_btn.clicked.connect(self.clear_history)
        side_layout.addWidget(self.clear_history_btn)

        splitter.addWidget(main_pane)
        splitter.addWidget(sidebar)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 2)

        root_layout.addWidget(splitter)
        self.setCentralWidget(root)

        self.src_text.textChanged.connect(self.schedule_translation)
        self.src_lang.changed.connect(self.schedule_translation)
        self.tgt_lang.changed.connect(self.schedule_translation)

        sb = self.history_view.verticalScrollBar()
        sb.valueChanged.connect(self._history_scroll_changed)

    def _build_tray(self):
        self.tray = QSystemTrayIcon(self.app_icon, self)
        self.tray.setToolTip(APP_NAME)

        menu = QMenu()
        self.tray_act_show_hide = QAction("Show", self)
        self.tray_act_show_hide.triggered.connect(self.toggle_visible)
        menu.addAction(self.tray_act_show_hide)

        menu.addSeparator()
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.quit_app)
        menu.addAction(act_quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    # Settings/history ----------------------------------------------------

    def _load_settings(self):
        settings = self.store.load_settings()
        self.src_lang.set_lang_code(settings.get("last_source_lang", "auto"))
        self.tgt_lang.set_lang_code(settings.get("last_target_lang", "en"))
        backend = settings.get("backend", "OpenAI")
        if backend not in BACKENDS:
            backend = "OpenAI"
        self.current_backend = backend
        self._select_backend_action(backend)

    def _save_settings(self):
        settings = {
            "last_source_lang": self.src_lang.current_lang_code(),
            "last_target_lang": self.tgt_lang.current_lang_code(),
            "backend": self.current_backend,
        }
        self.store.save_settings(settings)

    def _load_history_initial(self):
        self._history_lines = self.store.read_history_lines()
        self._history_loaded = 0
        self.history_model.clear()
        self._load_more_history()
        self._update_history_controls()

    def _load_more_history(self):
        # history.jsonl is oldest->newest (append). UI needs newest->oldest.
        total = len(self._history_lines)
        if total == 0:
            return

        start = self._history_loaded
        end = min(self._history_loaded + HISTORY_CHUNK, total)
        if start >= end:
            return

        recs: List[TranslationRecord] = []
        # newest line index: total-1, then backwards
        for i in range(start, end):
            line = self._history_lines[total - 1 - i]
            try:
                obj = json.loads(line)
                recs.append(TranslationRecord(**obj))
            except Exception:
                continue

        self.history_model.add_records(recs)
        self._history_loaded = end

    # Translation flow ----------------------------------------------------

    @contextmanager
    def _suspend_scheduling(self):
        prev = self._suppress_schedule
        self._suppress_schedule = True
        # Cancel any queued translation that might fire during programmatic updates.
        self._debounce.stop()
        try:
            yield
        finally:
            self._suppress_schedule = prev

    def schedule_translation(self):
        if self._suppress_schedule or not self._ui_enabled or not self.current_backend:
            return
        self._save_settings()
        self._debounce.start(DEBOUNCE_MS)

    def _is_duplicate_job(self, job: TranslateJob) -> bool:
        # Skip firing another translation if inputs match the most recent intent.
        return any(
            existing is not None and existing == job
            for existing in (self._latest_job, self._pending_job, self._active_job)
        )

    def _maybe_start_translation(self):
        if not self._ui_enabled or not self.current_backend:
            return
        text = (self.src_text.toPlainText() or "").strip()
        if not text:
            self._latest_job = None
            self._pending_job = None
            self._update_status()
            return

        job = TranslateJob(
            backend=self.current_backend,
            source_lang=self.src_lang.current_lang_code(),
            target_lang=self.tgt_lang.current_lang_code(),
            text=text,
        )

        if self._is_duplicate_job(job):
            return

        self._latest_job = job

        if self._in_flight:
            # Coalesce: keep only latest request to run after current finishes.
            self._pending_job = job
            self._update_status()
            return

        self._start_job(job)

    def _start_job(self, job: TranslateJob):
        if not self._ui_enabled or not self.current_backend:
            return
        self._in_flight = True
        self._pending_job = None
        self._active_job = job
        self._update_status()

        self._thread = QThread(self)
        self._worker = TranslatorWorker(job.backend, job)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.started.connect(self._on_worker_started)
        self._worker.finished.connect(self._on_job_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

    def _on_worker_started(self):
        self._set_status_text("Translating… (1 in flight)")

    def _on_job_finished(self, translated: str, err: str):
        job = self._active_job
        self._active_job = None
        self._in_flight = False

        if job is None:
            self._set_status_text("Idle")
            self._update_status()
            return

        if err:
            self._set_status_text(f"Error: {err}")
        else:
            self.tgt_text.blockSignals(True)
            self.tgt_text.setPlainText(translated)
            self.tgt_text.blockSignals(False)

            rec = TranslationRecord(
                ts=time.time(),
                backend=job.backend,
                model=OPENAI_TRANSLATION_MODEL if job.backend == "OpenAI" else "",
                source_lang=job.source_lang,
                target_lang=job.target_lang,
                source_text=job.text,
                target_text=translated,
            )
            self.store.append_history(rec)

            # Update history cache + list model at top
            self._history_lines.append(json.dumps(rec.__dict__, ensure_ascii=False))
            item = QStandardItem(self.history_model.format_item(rec))
            item.setEditable(False)
            item.setData(rec, Qt.UserRole)
            self.history_model.insertRow(0, item)
            self._history_loaded += 1  # because we added one visible record at top
            self._update_history_controls()

            self._set_status_text("Idle")

        # If something newer arrived while we were working, run it now (only latest)
        if self._pending_job is not None:
            pending = self._pending_job
            self._pending_job = None

            if pending.text.strip():
                self._start_job(pending)
                return

        self._update_status()

    # History interactions ------------------------------------------------

    def on_history_clicked(self, index: QModelIndex):
        rec = self.history_model.data(index, Qt.UserRole)
        if not isinstance(rec, TranslationRecord):
            if isinstance(rec, dict):
                try:
                    rec = TranslationRecord(**rec)
                except Exception:
                    return
            else:
                return

        with self._suspend_scheduling():
            self.src_lang.set_lang_code(rec.source_lang)
            self.tgt_lang.set_lang_code(rec.target_lang)
            self.src_text.setPlainText(rec.source_text)
            self.tgt_text.setPlainText(rec.target_text)

    def _history_scroll_changed(self, value: int):
        sb = self.history_view.verticalScrollBar()
        if value >= sb.maximum() - 20:
            self._load_more_history()

    def clear_history(self):
        if not self._history_lines and self.history_model.rowCount() == 0:
            return

        self.store.clear_history()
        self._history_lines = []
        self._history_loaded = 0
        self.history_model.clear()
        self._update_history_controls()

    def _update_history_controls(self):
        has_history = bool(self._history_lines) or self.history_model.rowCount() > 0
        self.clear_history_btn.setEnabled(has_history)

    # Backend selection ---------------------------------------------------

    def _select_backend_action(self, name: str) -> None:
        for backend_name, act in self.backend_actions.items():
            if backend_name in BACKENDS:
                act.setChecked(backend_name == name)

    def _uncheck_backend_action(self, name: str) -> None:
        act = self.backend_actions.get(name)
        if act:
            act.setChecked(False)

    def set_backend(
        self, name: str, prompt_if_missing: bool = True, schedule: bool = True
    ):
        if name not in BACKENDS:
            return
        previous_backend = self.current_backend
        if not self._ensure_backend_ready(name, prompt_if_missing=prompt_if_missing):
            self._uncheck_backend_action(name)
            self.current_backend = None
            self._set_ui_enabled(False, reason="OpenAI API key required.")
            return

        self.current_backend = name
        self._select_backend_action(name)
        self._set_ui_enabled(True)

        if schedule and name != previous_backend:
            self.schedule_translation()
        else:
            self._save_settings()

    def _ensure_backend_ready(self, name: str, prompt_if_missing: bool = True) -> bool:
        if name == "OpenAI":
            return self._configure_openai_api_key(prompt_if_missing=prompt_if_missing)
        return True

    def _configure_openai_api_key(self, prompt_if_missing: bool = True) -> bool:
        backend = BACKENDS["OpenAI"]
        if backend.has_api_key():
            return True

        stored = keyring.get_password(APP_NAME, "OpenAI")
        if stored:
            backend.set_api_key(stored)
            return True

        if not prompt_if_missing:
            return False

        key = self._prompt_for_openai_api_key()
        if key:
            keyring.set_password(APP_NAME, "OpenAI", key)
            backend.set_api_key(key)
            return True
        return False

    def _prompt_for_openai_api_key(self) -> Optional[str]:
        dialog = QDialog(self)
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

        def accept_if_present():
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

    # Swap ---------------------------------------------------------------

    def swap_languages_and_text(self):
        s_code = self.src_lang.current_lang_code()
        t_code = self.tgt_lang.current_lang_code()
        s_text = self.src_text.toPlainText()
        t_text = self.tgt_text.toPlainText()

        self.src_lang.set_lang_code(t_code if t_code else "auto")
        self.tgt_lang.set_lang_code(s_code if s_code and s_code != "auto" else "en")

        self.src_text.setPlainText(t_text)
        self.tgt_text.setPlainText(s_text)

        self.schedule_translation()

    # Tray / window lifecycle --------------------------------------------

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_visible()

    def toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()
        self._sync_show_hide_labels()

    def _sync_show_hide_labels(self):
        visible = self.isVisible()
        self.act_show_hide.setText("Hide" if visible else "Show")
        self.tray_act_show_hide.setText("Hide" if visible else "Show")

    def closeEvent(self, event):
        # Hide to tray instead of quitting.
        event.ignore()
        self.hide()
        self._sync_show_hide_labels()

    def quit_app(self):
        self._save_settings()
        self.tray.hide()
        QApplication.quit()

    # Status -------------------------------------------------------------

    def _set_ui_enabled(self, enabled: bool, reason: Optional[str] = None):
        self._ui_enabled = enabled
        self._ui_disabled_reason = None if enabled else (reason or "Backend not configured.")
        cw = self.centralWidget()
        if cw is not None:
            cw.setEnabled(enabled)
        self._update_status()

    def _set_status_text(self, txt: str):
        self.status_label.setText(txt)

    def _update_status(self):
        if not self._ui_enabled:
            self._set_status_text(self._ui_disabled_reason or "Backend not configured.")
            self._sync_show_hide_labels()
            return
        if self._in_flight:
            pending = 1 if self._pending_job is not None else 0
            self._set_status_text(f"Translating… (pending: {pending})")
        else:
            self._set_status_text("Idle")
        self._sync_show_hide_labels()

    # About --------------------------------------------------------------

    def show_about(self):
        QMessageBox.information(
            self,
            "About tl",
            f"{APP_NAME}\n\n"
            "- PySide6 translator UI\n"
            "- Backend: OpenAI (extensible)\n"
            "- Data stored in applicationDirPath:\n"
            f"  {self.base_dir}\n",
        )
