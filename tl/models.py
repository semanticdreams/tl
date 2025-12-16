from dataclasses import dataclass


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
