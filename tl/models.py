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
    context_text: str = ""


@dataclass
class TranslateJob:
    backend: str
    source_lang: str
    target_lang: str
    text: str
    context_text: str = ""


@dataclass
class InfoJob:
    backend: str
    source_lang: str
    target_lang: str
    source_text: str
    target_text: str
    kind: str
    output_lang: str


@dataclass
class AudioJob:
    backend: str
    target_lang: str
    text: str
    voice: str
    response_format: str
