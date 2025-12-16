from typing import Dict

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
