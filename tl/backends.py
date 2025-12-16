from typing import Dict, Optional

# OpenAI SDK (official)
from openai import OpenAI

from .constants import OPENAI_TRANSLATION_MODEL


class TranslationBackend:
    name: str = "Base"

    def translate(self, source_lang: str, target_lang: str, text: str) -> str:
        raise NotImplementedError


class OpenAIBackend(TranslationBackend):
    name = "OpenAI"

    def __init__(self):
        self.client: Optional[OpenAI] = None
        self._api_key: Optional[str] = None

    def translate(self, source_lang: str, target_lang: str, text: str) -> str:
        if not self.client:
            raise RuntimeError("OpenAI API key not configured.")

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

    def set_api_key(self, api_key: str) -> None:
        self._api_key = api_key
        self.client = OpenAI(api_key=api_key)

    def has_api_key(self) -> bool:
        return bool(self._api_key)


BACKENDS: Dict[str, TranslationBackend] = {
    "OpenAI": OpenAIBackend(),
    # Future:
    # "DeepL": ...
    # "Google Translate": ...
}
