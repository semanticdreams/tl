from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import (
    Qt,
    QTimer,
    QThread,
    QModelIndex,
    QStandardPaths,
    QBuffer,
    QByteArray,
    QIODevice,
    QSettings,
    QEvent,
)
from PySide6.QtGui import QAction, QIcon, QStandardItem
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QSystemTrayIcon

import keyring

from .audio import prepend_wav_silence
from .backends import BACKENDS
from .cache import TranslationCache
from .constants import APP_NAME, DEBOUNCE_MS, HISTORY_CHUNK, OPENAI_TRANSLATION_MODEL
from .dialogs import prompt_for_openai_api_key, show_about, SettingsDialog
from .models import TranslateJob, TranslationRecord, InfoJob, AudioJob
from .persistence import Persistence
from .resources import load_icon
from .ui import build_main_ui, build_tray
from .worker import TranslatorWorker, InfoWorker, AudioWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setObjectName(APP_NAME)
        self.app_icon: QIcon = load_icon()
        self.setWindowIcon(self.app_icon)

        self.app_settings = QSettings(APP_NAME, APP_NAME)
        self.base_dir = Path(
            QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        )
        self.store = Persistence(self.base_dir)
        self.cache = TranslationCache(self.store)

        self.current_backend = "OpenAI"
        self._ui_enabled = True
        self._ui_disabled_reason: Optional[str] = None
        self._suppress_schedule = False
        self._auto_translate = True
        self._extra_info_lang = "target"
        self._start_minimized = False
        self._minimize_to_tray = True
        self._load_app_settings()

        # Translation scheduling/coalescing
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._maybe_start_translation)

        self._in_flight = False
        self._pending_job: Optional[TranslateJob] = None
        self._active_job: Optional[TranslateJob] = None
        self._latest_job: Optional[TranslateJob] = None  # last requested intent
        self._info_in_flight = False
        self._info_kind: Optional[str] = None
        self._info_job: Optional[InfoJob] = None
        self._audio_in_flight = False
        self._audio_job: Optional[AudioJob] = None
        self._audio_voice = "alloy"
        self._audio_response_format = "wav"
        self._audio_cancel_requested = False
        self._audio_playing = False
        self._audio_pending_play = False

        self.audio_output = QAudioOutput(self)
        self.audio_player = QMediaPlayer(self)
        self.audio_player.setAudioOutput(self.audio_output)
        self.audio_player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.audio_player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._audio_buffer: Optional[QBuffer] = None

        # History
        self._history_lines: List[str] = []
        self._history_loaded = 0  # how many items loaded into list model (from newest)
        self._build_ui()
        self._build_tray()
        self._load_settings()
        self.set_backend(self.current_backend, prompt_if_missing=True, schedule=False)
        self._load_history_initial()

        self._update_status()

    # UI ------------------------------------------------------------------

    def _build_ui(self):
        build_main_ui(self)

    def _build_tray(self):
        build_tray(self)

    # Settings/history ----------------------------------------------------

    def _load_app_settings(self) -> None:
        self._start_minimized = self.app_settings.value(
            "ui/start_minimized", False, type=bool
        )
        self._minimize_to_tray = self.app_settings.value(
            "ui/minimize_to_tray", True, type=bool
        )

    def _save_app_settings(self) -> None:
        self.app_settings.setValue("ui/start_minimized", self._start_minimized)
        self.app_settings.setValue("ui/minimize_to_tray", self._minimize_to_tray)
        self.app_settings.sync()

    def _load_settings(self):
        settings = self.store.load_settings()
        self.src_lang.set_lang_code(settings.get("last_source_lang", "auto"))
        self.tgt_lang.set_lang_code(settings.get("last_target_lang", "en"))
        self._auto_translate = settings.get("auto_translate", True)
        self._extra_info_lang = settings.get("extra_info_language", "target")
        self.auto_translate_checkbox.setChecked(self._auto_translate)
        self.submit_btn.setEnabled(not self._auto_translate)
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
            "auto_translate": self._auto_translate,
            "extra_info_language": self._extra_info_lang,
        }
        self.store.save_settings(settings)

    def show_settings(self) -> None:
        dialog = SettingsDialog(
            self,
            start_minimized=self._start_minimized,
            minimize_to_tray=self._minimize_to_tray,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self._start_minimized = dialog.start_minimized_checkbox.isChecked()
        self._minimize_to_tray = dialog.minimize_to_tray_checkbox.isChecked()
        self._save_app_settings()
        if not self._minimize_to_tray and not self.isVisible():
            self.showNormal()
        self._sync_show_hide_labels()

    def apply_startup_visibility(self) -> None:
        if not self._start_minimized:
            return
        if self._minimize_to_tray:
            self.hide()
        else:
            self.showMinimized()
        self._sync_show_hide_labels()

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
        self._clear_extra_info()
        if not self._auto_translate:
            return
        self._save_settings()
        self._debounce.start(DEBOUNCE_MS)

    def trigger_translation_now(self):
        if (
            self._suppress_schedule
            or not self._ui_enabled
            or not self.current_backend
            or self._auto_translate
        ):
            return
        self._clear_extra_info()
        self._save_settings()
        self._debounce.stop()
        self._maybe_start_translation()

    def _on_auto_translate_toggled(self, checked: bool) -> None:
        self._auto_translate = checked
        self.submit_btn.setEnabled(not checked)
        if checked:
            self.schedule_translation()
        else:
            self._debounce.stop()

    def clear_source_and_context(self) -> None:
        with self._suspend_scheduling():
            self.src_text.clear()
            self.context_text.clear()
        self._clear_extra_info()

    def _is_duplicate_job(self, job: TranslateJob) -> bool:
        # Skip firing another translation if inputs match the most recent intent.
        return any(
            existing is not None and existing == job
            for existing in (self._latest_job, self._pending_job, self._active_job)
        )

    def _current_job_snapshot(self) -> Optional[TranslateJob]:
        if not self.current_backend:
            return None
        text = (self.src_text.toPlainText() or "").strip()
        if not text:
            return None
        return TranslateJob(
            backend=self.current_backend,
            source_lang=self.src_lang.current_lang_code(),
            target_lang=self.tgt_lang.current_lang_code(),
            text=text,
            context_text=(self.context_text.toPlainText() or "").strip(),
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
            context_text=(self.context_text.toPlainText() or "").strip(),
        )

        if self._is_duplicate_job(job):
            return

        self._latest_job = job

        if self._in_flight:
            # Coalesce: keep only latest request to run after current finishes.
            self._pending_job = job
            self._update_status()
            return

        cached = self.cache.get_translation(job)
        if cached is not None:
            self._apply_translation_result(job, cached, from_cache=True)
            self._update_status()
            return

        self._start_job(job)

    def _start_job(self, job: TranslateJob):
        if not self._ui_enabled or not self.current_backend:
            return
        cached = self.cache.get_translation(job)
        if cached is not None:
            self._apply_translation_result(job, cached, from_cache=True)
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
        self._set_status_text("Translating... (1 in flight)")

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
            self._apply_translation_result(job, translated, from_cache=False)

        # If something newer arrived while we were working, run it now (only latest)
        if self._pending_job is not None:
            pending = self._pending_job
            self._pending_job = None

            if pending.text.strip():
                self._start_job(pending)
                return

        self._update_status()

    def _apply_translation_result(
        self, job: TranslateJob, translated: str, from_cache: bool
    ) -> None:
        if not from_cache:
            self.cache.set_translation(job, translated)
        self.tgt_text.blockSignals(True)
        self.tgt_text.setPlainText(translated)
        self.tgt_text.blockSignals(False)
        self._clear_extra_info()

        rec = TranslationRecord(
            ts=time.time(),
            backend=job.backend,
            model=OPENAI_TRANSLATION_MODEL if job.backend == "OpenAI" else "",
            source_lang=job.source_lang,
            target_lang=job.target_lang,
            source_text=job.text,
            target_text=translated,
            context_text=job.context_text,
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

    def request_extra_info(self, kind: str):
        if not self._ui_enabled or not self.current_backend:
            return
        if self._info_in_flight:
            return
        if not self._ensure_backend_ready(self.current_backend, prompt_if_missing=True):
            self._set_ui_enabled(False, reason="OpenAI API key required.")
            return

        source_text = (self.src_text.toPlainText() or "").strip()
        target_text = (self.tgt_text.toPlainText() or "").strip()
        if not target_text:
            self._set_extra_text("Translate something first.")
            return
        if kind == "etymology":
            if len(target_text.split()) != 1:
                self._set_extra_text("Etymology is available for single words only.")
                return

        output_lang = self.tgt_lang.current_lang_code()
        if kind in {"usage", "grammar", "etymology"} and self._extra_info_lang == "source":
            output_lang = self.src_lang.current_lang_code()
            if output_lang == "auto":
                output_lang = "source language"

        job = InfoJob(
            backend=self.current_backend,
            source_lang=self.src_lang.current_lang_code(),
            target_lang=self.tgt_lang.current_lang_code(),
            source_text=source_text,
            target_text=target_text,
            kind=kind,
            output_lang=output_lang,
        )
        cached = self.cache.get_info(job)
        if cached is not None:
            self._set_extra_text(cached)
            return
        self._start_info_job(job)

    def request_speak(self) -> None:
        if not self._ui_enabled or not self.current_backend:
            return
        if self._audio_in_flight:
            self._audio_cancel_requested = True
            self._set_status_text("Audio canceled.")
            self._set_speak_button_state(in_progress=False)
            return
        if self._audio_playing:
            self._stop_audio_playback()
            return
        if not self._ensure_backend_ready(self.current_backend, prompt_if_missing=True):
            self._set_ui_enabled(False, reason="OpenAI API key required.")
            return

        target_text = (self.tgt_text.toPlainText() or "").strip()
        if not target_text:
            self._set_status_text("Nothing to speak.")
            return

        self._audio_cancel_requested = False
        job = AudioJob(
            backend=self.current_backend,
            target_lang=self.tgt_lang.current_lang_code(),
            text=target_text,
            voice=self._audio_voice,
            response_format=self._audio_response_format,
        )
        cached = self.cache.get_audio(job)
        if cached is not None:
            self._play_audio(cached)
            return
        self._start_audio_job(job)

    def _start_audio_job(self, job: AudioJob) -> None:
        self._audio_in_flight = True
        self._audio_job = job
        self._set_speak_button_state(in_progress=True)
        self._set_status_text("Fetching audio...")
        self._update_status()

        self._audio_thread = QThread(self)
        self._audio_worker = AudioWorker(job.backend, job)
        self._audio_worker.moveToThread(self._audio_thread)

        self._audio_thread.started.connect(self._audio_worker.run)
        self._audio_worker.started.connect(self._on_audio_started)
        self._audio_worker.finished.connect(self._on_audio_finished)
        self._audio_worker.finished.connect(self._audio_thread.quit)
        self._audio_worker.finished.connect(self._audio_worker.deleteLater)
        self._audio_thread.finished.connect(self._audio_thread.deleteLater)

        self._audio_thread.start()

    def _on_audio_started(self) -> None:
        self._update_status()

    def _on_audio_finished(self, audio: bytes, err: str) -> None:
        self._audio_in_flight = False
        self._set_speak_button_state(in_progress=False)
        if err:
            self._set_status_text(f"Error: {err}")
            self._audio_job = None
            self._sync_show_hide_labels()
            return
        else:
            if self._audio_cancel_requested:
                self._audio_job = None
                self._audio_cancel_requested = False
                self._set_status_text("Audio canceled.")
                self._update_status()
                return
            if self._audio_job is not None:
                self.cache.set_audio(self._audio_job, audio)
            self._play_audio(audio)
        self._audio_job = None
        self._update_status()

    def _play_audio(self, audio: bytes) -> None:
        if not audio:
            self._set_status_text("No audio returned.")
            return
        audio = prepend_wav_silence(audio, seconds=0.1)
        self._stop_audio_playback()
        self._set_speak_button_state(in_progress=True)
        self._audio_buffer = QBuffer(self)
        self._audio_buffer.setData(QByteArray(audio))
        self._audio_buffer.open(QIODevice.ReadOnly)
        self._audio_playing = True
        self._audio_pending_play = True
        self.audio_player.setSourceDevice(self._audio_buffer)
        if self.audio_player.mediaStatus() in (
            QMediaPlayer.LoadedMedia,
            QMediaPlayer.BufferedMedia,
        ):
            self._audio_pending_play = False
            self.audio_player.play()

    def _set_speak_button_state(self, in_progress: bool) -> None:
        if in_progress:
            self.speak_btn.setText("Cancel s&peak")
            self.speak_btn.setToolTip("Cancel speaking or audio fetch.")
        else:
            self.speak_btn.setText("S&peak")
            self.speak_btn.setToolTip("Speak the translated text.")

    def _stop_audio_playback(self) -> None:
        self.audio_player.stop()
        self._audio_playing = False
        self._audio_pending_play = False
        if self._audio_buffer is not None:
            self._audio_buffer.close()
            self._audio_buffer = None
        self._set_speak_button_state(in_progress=False)

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if (
            status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia)
            and self._audio_pending_play
        ):
            self._audio_pending_play = False
            self.audio_player.play()

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.StoppedState:
            if not self._audio_in_flight:
                self._set_speak_button_state(in_progress=False)
            self._audio_playing = False

    def _set_extra_text(self, text: str) -> None:
        self.extra_text.blockSignals(True)
        self.extra_text.setPlainText(text)
        self.extra_text.blockSignals(False)
        self.extra_text.setEnabled(True)

    def _clear_extra_info(self) -> None:
        self.extra_text.blockSignals(True)
        self.extra_text.setPlainText("")
        self.extra_text.blockSignals(False)
        self.extra_text.setEnabled(False)

    def _set_info_buttons_enabled(self, enabled: bool) -> None:
        self.examples_btn.setEnabled(enabled)
        self.alternatives_btn.setEnabled(enabled)
        self.etymology_btn.setEnabled(enabled)
        self.synonyms_btn.setEnabled(enabled)
        self.antonyms_btn.setEnabled(enabled)
        self.usage_btn.setEnabled(enabled)
        self.grammar_btn.setEnabled(enabled)

    def _show_extra_text_context_menu(self, pos) -> None:
        menu = self.extra_text.createStandardContextMenu()
        menu.addSeparator()
        lang_menu = menu.addMenu("Language")
        source_action = QAction("Source", menu)
        source_action.setCheckable(True)
        source_action.setChecked(self._extra_info_lang == "source")
        target_action = QAction("Target", menu)
        target_action.setCheckable(True)
        target_action.setChecked(self._extra_info_lang != "source")

        def set_lang(value: str) -> None:
            self._extra_info_lang = value
            self._save_settings()

        source_action.triggered.connect(lambda: set_lang("source"))
        target_action.triggered.connect(lambda: set_lang("target"))
        lang_menu.addAction(source_action)
        lang_menu.addAction(target_action)
        menu.exec(self.extra_text.mapToGlobal(pos))

    def _start_info_job(self, job: InfoJob) -> None:
        self._info_in_flight = True
        self._info_kind = job.kind
        self._info_job = job
        self._set_info_buttons_enabled(False)
        self._update_status()

        self._info_thread = QThread(self)
        self._info_worker = InfoWorker(job.backend, job)
        self._info_worker.moveToThread(self._info_thread)

        self._info_thread.started.connect(self._info_worker.run)
        self._info_worker.started.connect(self._on_info_started)
        self._info_worker.finished.connect(self._on_info_finished)
        self._info_worker.finished.connect(self._info_thread.quit)
        self._info_worker.finished.connect(self._info_worker.deleteLater)
        self._info_thread.finished.connect(self._info_thread.deleteLater)

        self._info_thread.start()

    def _on_info_started(self) -> None:
        self._update_status()

    def _on_info_finished(self, info: str, err: str) -> None:
        self._info_in_flight = False
        self._set_info_buttons_enabled(True)
        if err:
            self._set_extra_text(f"Error: {err}")
        else:
            if self._info_job is not None:
                self.cache.set_info(self._info_job, info)
            self._set_extra_text(info)
        self._info_kind = None
        self._info_job = None
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
            self.context_text.setPlainText(getattr(rec, "context_text", ""))
            self.tgt_text.setPlainText(rec.target_text)
            self._clear_extra_info()
        snap = self._current_job_snapshot()
        if snap:
            self._latest_job = snap
            self._pending_job = None

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

        key = prompt_for_openai_api_key(self)
        if key:
            keyring.set_password(APP_NAME, "OpenAI", key)
            backend.set_api_key(key)
            return True
        return False

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
        self._clear_extra_info()

        self.schedule_translation()

    # Tray / window lifecycle --------------------------------------------

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_visible()

    def toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()
        self._sync_show_hide_labels()

    def _sync_show_hide_labels(self):
        visible = self.isVisible()
        self.act_show_hide.setText("Hide" if visible else "Show")
        self.tray_act_show_hide.setText("Hide" if visible else "Show")

    def closeEvent(self, event):
        if self._minimize_to_tray:
            event.ignore()
            self.hide()
            self._sync_show_hide_labels()
            return
        event.accept()
        self.quit_app()

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange:
            if self._minimize_to_tray and self.isMinimized():
                QTimer.singleShot(0, self._hide_after_minimize)
        super().changeEvent(event)

    def _hide_after_minimize(self) -> None:
        if self._minimize_to_tray and self.isMinimized():
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
        if self._in_flight and self._info_in_flight:
            kind = self._info_kind or "info"
            pending = 1 if self._pending_job is not None else 0
            self._set_status_text(f"Translating... (pending: {pending}); {kind}...")
        elif self._in_flight:
            pending = 1 if self._pending_job is not None else 0
            self._set_status_text(f"Translating... (pending: {pending})")
        elif self._info_in_flight:
            kind = self._info_kind or "info"
            self._set_status_text(f"Fetching {kind}...")
        elif self._audio_in_flight:
            self._set_status_text("Fetching audio...")
        else:
            self._set_status_text("Idle")
        self._sync_show_hide_labels()

    # About --------------------------------------------------------------

    def show_about(self):
        show_about(self, self.base_dir)
