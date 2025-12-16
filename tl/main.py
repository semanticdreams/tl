# tl.py
# A minimal translator UI tool with PySide6 + OpenAI backend
# Features:
# - systray (close => hide), show/hide + quit
# - debounced translation (1000ms) on input/lang change/swap
# - one request at a time, coalesces pending changes
# - persistence in applicationDirPath: settings.json + history.jsonl
# - history sidebar newest->oldest, incremental loading on scroll

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Tuple

from PySide6.QtCore import (
    Qt, QTimer, QThread, Signal, QObject, QCoreApplication, QModelIndex
)
from PySide6.QtGui import QAction, QIcon, QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPlainTextEdit,
    QComboBox, QPushButton, QListView, QSplitter, QStatusBar, QSystemTrayIcon,
    QMenu, QMessageBox, QLabel
)
from importlib import resources

# OpenAI SDK (official)
from openai import OpenAI  # pip install openai



def load_icon():
    with resources.path("tl.assets", "icon.png") as p:
        return QIcon(str(p))


APP_NAME = "tl"
DEBOUNCE_MS = 1000
HISTORY_CHUNK = 50

# Cheapest solid text model for focused tasks like translation.
OPENAI_TRANSLATION_MODEL = "gpt-4o-mini"


# --- Data models -------------------------------------------------------------

@dataclass
class TranslationRecord:
    ts: float
    backend: str
    model: str
    source_lang: str
    target_lang: str
    source_text: str
    target_text: str


@dataclass
class TranslateJob:
    backend: str
    source_lang: str
    target_lang: str
    text: str


# --- Persistence -------------------------------------------------------------

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


# --- Language list -----------------------------------------------------------

# Simple curated set; easy to expand.
# Use BCP-47-ish codes where possible.
LANGUAGES: List[Tuple[str, str]] = [
    ("auto", "Auto Detect"),
    ("en", "English"),
    ("de", "German"),
    ("fr", "French"),
    ("es", "Spanish"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
    ("nl", "Dutch"),
    ("sv", "Swedish"),
    ("no", "Norwegian"),
    ("da", "Danish"),
    ("fi", "Finnish"),
    ("pl", "Polish"),
    ("cs", "Czech"),
    ("sk", "Slovak"),
    ("hu", "Hungarian"),
    ("ro", "Romanian"),
    ("bg", "Bulgarian"),
    ("el", "Greek"),
    ("tr", "Turkish"),
    ("uk", "Ukrainian"),
    ("ru", "Russian"),
    ("ar", "Arabic"),
    ("he", "Hebrew"),
    ("fa", "Persian"),
    ("hi", "Hindi"),
    ("bn", "Bengali"),
    ("th", "Thai"),
    ("vi", "Vietnamese"),
    ("id", "Indonesian"),
    ("ms", "Malay"),
    ("zh", "Chinese"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
]
LANG_NAME_BY_CODE = {c: n for c, n in LANGUAGES}


# --- Language combo box ------------------------------------------------------

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


# --- Translation backends (extensible) --------------------------------------

class TranslationBackend:
    name: str = "Base"
    def translate(self, source_lang: str, target_lang: str, text: str) -> str:
        raise NotImplementedError


class OpenAIBackend(TranslationBackend):
    name = "OpenAI"

    def __init__(self):
        # Uses OPENAI_API_KEY env var by default
        self.client = OpenAI()

    def translate(self, source_lang: str, target_lang: str, text: str) -> str:
        source_desc = "auto-detect" if source_lang == "auto" else f"{source_lang}"
        prompt = (
            "You are a high-accuracy translation engine.\n"
            "Rules:\n"
            "- Output ONLY the translated text.\n"
            "- Preserve meaning, tone, formatting, punctuation.\n"
            "- Do not add explanations.\n\n"
            f"Translate from {source_desc} to {target_lang}:\n\n{text}"
        )

        # Responses API (recommended in current OpenAI docs)
        resp = self.client.responses.create(
            model=OPENAI_TRANSLATION_MODEL,
            input=prompt,
            temperature=0,
        )
        out = (getattr(resp, "output_text", None) or "").strip()
        return out


BACKENDS: Dict[str, TranslationBackend] = {
    "OpenAI": OpenAIBackend(),
    # Future:
    # "DeepL": ...
    # "Google Translate": ...
}


# --- Worker thread (one at a time) ------------------------------------------

class TranslatorWorker(QObject):
    finished = Signal(str, str)   # (translated_text, error_message)
    started = Signal()

    def __init__(self, backend_name: str, job: TranslateJob):
        super().__init__()
        self.backend_name = backend_name
        self.job = job

    def run(self):
        self.started.emit()
        try:
            backend = BACKENDS[self.backend_name]
            translated = backend.translate(self.job.source_lang, self.job.target_lang, self.job.text)
            self.finished.emit(translated, "")
        except Exception as e:
            self.finished.emit("", str(e))


# --- History model (incremental loading) -------------------------------------

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


# --- Main window -------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setObjectName(APP_NAME)
        self.app_icon = load_icon()
        self.setWindowIcon(self.app_icon)

        self.base_dir = QCoreApplication.applicationDirPath()
        self.store = Persistence(self.base_dir)

        self.current_backend = "OpenAI"
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
        self._load_history_initial()

        self._update_status()

    # UI ---------------------------------------------------------------------

    def _build_ui(self):
        self.setStatusBar(QStatusBar(self))
        self.status_label = QLabel("Idle")
        self.statusBar().addPermanentWidget(self.status_label)

        # Menubar
        mb = self.menuBar()

        file_menu = mb.addMenu("&File")
        self.act_show_hide = QAction("Hide", self)
        self.act_show_hide.triggered.connect(self.toggle_visible)
        file_menu.addAction(self.act_show_hide)

        file_menu.addSeparator()
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.quit_app)
        file_menu.addAction(act_quit)

        backend_menu = mb.addMenu("&Backend")  # between File and About
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

        # Central layout: main (source/swap/target) + right sidebar (history)
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

        # swap button
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
        side_layout.addWidget(self.history_view)

        splitter.addWidget(main_pane)
        splitter.addWidget(sidebar)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 2)

        root_layout.addWidget(splitter)
        self.setCentralWidget(root)

        # Signals => schedule translation
        self.src_text.textChanged.connect(self.schedule_translation)
        self.src_lang.changed.connect(self.schedule_translation)
        self.tgt_lang.changed.connect(self.schedule_translation)

        # Infinite scroll: when user scrolls near bottom, load more (older)
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

    # Settings/history --------------------------------------------------------

    def _load_settings(self):
        s = self.store.load_settings()
        self.src_lang.set_lang_code(s.get("last_source_lang", "auto"))
        self.tgt_lang.set_lang_code(s.get("last_target_lang", "en"))

    def _save_settings(self):
        s = {
            "last_source_lang": self.src_lang.current_lang_code(),
            "last_target_lang": self.tgt_lang.current_lang_code(),
            "backend": self.current_backend,
        }
        self.store.save_settings(s)

    def _load_history_initial(self):
        self._history_lines = self.store.read_history_lines()
        self._history_loaded = 0
        self.history_model.clear()
        self._load_more_history()

    def _load_more_history(self):
        # history.jsonl is oldest->newest (append). UI needs newest->oldest.
        total = len(self._history_lines)
        if total == 0:
            return

        # Compute slice in newest->oldest order
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

    # Translation flow --------------------------------------------------------

    @contextmanager
    def _suspend_scheduling(self):
        prev = self._suppress_schedule
        self._suppress_schedule = True
        self._debounce.stop()  # cancel any queued translation that might fire during programmatic updates
        try:
            yield
        finally:
            self._suppress_schedule = prev

    def schedule_translation(self):
        if self._suppress_schedule:
            return
        # Debounce requests
        self._save_settings()
        self._debounce.start(DEBOUNCE_MS)

    def _maybe_start_translation(self):
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
        self._latest_job = job

        if self._in_flight:
            # Coalesce: keep only latest request to run after current finishes
            self._pending_job = job
            self._update_status()
            return

        self._start_job(job)

    def _start_job(self, job: TranslateJob):
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
            # Keep app usable; don't crash
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
            self._history_lines.append(json.dumps(asdict(rec), ensure_ascii=False))
            item = QStandardItem(self.history_model.format_item(rec))
            item.setEditable(False)
            item.setData(rec, Qt.UserRole)
            self.history_model.insertRow(0, item)
            self._history_loaded += 1  # because we added one visible record at top

            self._set_status_text("Idle")

        # If something newer arrived while we were working, run it now (only latest)
        if self._pending_job is not None:
            pending = self._pending_job
            self._pending_job = None

            # If pending text is empty now, don't translate
            if pending.text.strip():
                self._start_job(pending)
                return

        self._update_status()

    # History interactions -----------------------------------------------------

    def on_history_clicked(self, index: QModelIndex):
        rec = self.history_model.data(index, Qt.UserRole)
        if not isinstance(rec, TranslationRecord):
            # PySide can return dict-like; handle both
            if isinstance(rec, dict):
                try:
                    rec = TranslationRecord(**rec)
                except Exception:
                    return
            else:
                return

        # Load record into panes (does not auto-translate unless user edits; we keep it simple)
        with self._suspend_scheduling():
            self.src_lang.set_lang_code(rec.source_lang)
            self.tgt_lang.set_lang_code(rec.target_lang)
            self.src_text.setPlainText(rec.source_text)
            self.tgt_text.setPlainText(rec.target_text)

    def _history_scroll_changed(self, value: int):
        sb = self.history_view.verticalScrollBar()
        # When close to bottom, load more older items
        if value >= sb.maximum() - 20:
            self._load_more_history()

    # Backend selection --------------------------------------------------------

    def set_backend(self, name: str):
        if name not in BACKENDS:
            return
        self.current_backend = name
        for k, act in self.backend_actions.items():
            if k in BACKENDS:
                act.setChecked(k == name)
        self.schedule_translation()

    # Swap --------------------------------------------------------------------

    def swap_languages_and_text(self):
        s_code = self.src_lang.current_lang_code()
        t_code = self.tgt_lang.current_lang_code()
        s_text = self.src_text.toPlainText()
        t_text = self.tgt_text.toPlainText()

        # Swap language selections
        self.src_lang.set_lang_code(t_code if t_code else "auto")
        self.tgt_lang.set_lang_code(s_code if s_code and s_code != "auto" else "en")

        # Swap text contents
        self.src_text.setPlainText(t_text)
        self.tgt_text.setPlainText(s_text)

        self.schedule_translation()

    # Tray / window lifecycle -------------------------------------------------

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:  # single click
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
        # Hide to tray instead of quitting
        event.ignore()
        self.hide()
        self._sync_show_hide_labels()
        self.tray.showMessage(APP_NAME, "Still running in system tray.", self.app_icon, 1500)

    def quit_app(self):
        self._save_settings()
        self.tray.hide()
        QApplication.quit()

    # Status ------------------------------------------------------------------

    def _set_status_text(self, txt: str):
        self.status_label.setText(txt)

    def _update_status(self):
        if self._in_flight:
            pending = 1 if self._pending_job is not None else 0
            self._set_status_text(f"Translating… (pending: {pending})")
        else:
            self._set_status_text("Idle")
        self._sync_show_hide_labels()

    # About -------------------------------------------------------------------

    def show_about(self):
        QMessageBox.information(
            self,
            "About tl",
            f"{APP_NAME}\n\n"
            "- PySide6 translator UI\n"
            "- Backend: OpenAI (extensible)\n"
            "- Data stored in applicationDirPath:\n"
            f"  {self.base_dir}\n"
        )


def main():
    app = QApplication([])
    app.setApplicationName(APP_NAME)

    w = MainWindow()
    w.resize(1200, 700)
    w.show()

    app.exec()


if __name__ == "__main__":
    main()
