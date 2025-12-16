from PySide6.QtCore import QObject, Signal

from .backends import BACKENDS
from .models import TranslateJob


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
                self.job.source_lang, self.job.target_lang, self.job.text
            )
            self.finished.emit(translated, "")
        except Exception as exc:
            self.finished.emit("", str(exc))
