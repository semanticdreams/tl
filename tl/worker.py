from PySide6.QtCore import QObject, Signal

from .backends import BACKENDS
from .models import TranslateJob, InfoJob, AudioJob


class TranslatorWorker(QObject):
    finished = Signal(str, str)  # (translated_text, error_message)
    started = Signal()

    def __init__(self, backend_name: str, job: TranslateJob):
        super().__init__()
        self.backend_name = backend_name
        self.job = job

    def run(self):
        self.started.emit()
        try:
            backend = BACKENDS[self.backend_name]
            translated = backend.translate(
                self.job.source_lang,
                self.job.target_lang,
                self.job.text,
                self.job.context_text,
            )
            self.finished.emit(translated, "")
        except Exception as exc:
            self.finished.emit("", str(exc))


class InfoWorker(QObject):
    finished = Signal(str, str)  # (info_text, error_message)
    started = Signal()

    def __init__(self, backend_name: str, job: InfoJob):
        super().__init__()
        self.backend_name = backend_name
        self.job = job

    def run(self):
        self.started.emit()
        try:
            backend = BACKENDS[self.backend_name]
            info = backend.generate_info(
                self.job.kind,
                self.job.source_lang,
                self.job.target_lang,
                self.job.source_text,
                self.job.target_text,
                self.job.output_lang,
            )
            self.finished.emit(info, "")
        except Exception as exc:
            self.finished.emit("", str(exc))


class AudioWorker(QObject):
    finished = Signal(bytes, str)  # (audio_bytes, error_message)
    started = Signal()

    def __init__(self, backend_name: str, job: AudioJob):
        super().__init__()
        self.backend_name = backend_name
        self.job = job

    def run(self):
        self.started.emit()
        try:
            backend = BACKENDS[self.backend_name]
            audio = backend.text_to_speech(
                self.job.text,
                voice=self.job.voice,
                response_format=self.job.response_format,
            )
            self.finished.emit(audio, "")
        except Exception as exc:
            self.finished.emit(b"", str(exc))
