from __future__ import annotations

import base64
import hashlib
from typing import Optional

from .models import AudioJob, InfoJob, TranslateJob
from .persistence import Persistence


class TranslationCache:
    def __init__(self, store: Persistence) -> None:
        self._store = store
        self._cache = store.load_cache()

    @staticmethod
    def _translation_cache_key(job: TranslateJob) -> str:
        digest = hashlib.sha256(job.text.encode("utf-8")).hexdigest()
        context_digest = hashlib.sha256(
            job.context_text.encode("utf-8")
        ).hexdigest()
        return (
            f"{job.backend}|{job.source_lang}|{job.target_lang}|"
            f"{digest}|{context_digest}"
        )

    @staticmethod
    def _info_cache_key(job: InfoJob) -> str:
        src_digest = hashlib.sha256(job.source_text.encode("utf-8")).hexdigest()
        tgt_digest = hashlib.sha256(job.target_text.encode("utf-8")).hexdigest()
        return (
            f"{job.backend}|{job.source_lang}|{job.target_lang}|{job.kind}|"
            f"{src_digest}|{tgt_digest}|{job.output_lang}"
        )

    @staticmethod
    def _audio_cache_key(job: AudioJob) -> str:
        tgt_digest = hashlib.sha256(job.text.encode("utf-8")).hexdigest()
        return (
            f"{job.backend}|{job.target_lang}|{job.voice}|"
            f"{job.response_format}|{tgt_digest}"
        )

    def get_translation(self, job: TranslateJob) -> Optional[str]:
        translations = self._cache.get("translations", {})
        return translations.get(self._translation_cache_key(job))

    def set_translation(self, job: TranslateJob, translated: str) -> None:
        key = self._translation_cache_key(job)
        translations = self._cache.setdefault("translations", {})
        translations[key] = translated
        self._store.save_cache(self._cache)

    def get_info(self, job: InfoJob) -> Optional[str]:
        info = self._cache.get("info", {})
        return info.get(self._info_cache_key(job))

    def set_info(self, job: InfoJob, info_text: str) -> None:
        key = self._info_cache_key(job)
        info = self._cache.setdefault("info", {})
        info[key] = info_text
        self._store.save_cache(self._cache)

    def get_audio(self, job: AudioJob) -> Optional[bytes]:
        audio = self._cache.get("audio", {})
        encoded = audio.get(self._audio_cache_key(job))
        if not encoded:
            return None
        try:
            return base64.b64decode(encoded.encode("ascii"))
        except Exception:
            return None

    def set_audio(self, job: AudioJob, audio_bytes: bytes) -> None:
        key = self._audio_cache_key(job)
        audio = self._cache.setdefault("audio", {})
        audio[key] = base64.b64encode(audio_bytes).decode("ascii")
        self._store.save_cache(self._cache)
