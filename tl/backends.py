from typing import Dict, Optional

# OpenAI SDK (official)
from openai import OpenAI

from .constants import OPENAI_TRANSLATION_MODEL, OPENAI_TTS_MODEL


class TranslationBackend:
    name: str = "Base"

    def translate(
        self, source_lang: str, target_lang: str, text: str, context_text: str = ""
    ) -> str:
        raise NotImplementedError

    def generate_info(
        self,
        kind: str,
        source_lang: str,
        target_lang: str,
        source_text: str,
        target_text: str,
        output_lang: str,
    ) -> str:
        raise NotImplementedError

    def text_to_speech(
        self, text: str, voice: str = "alloy", response_format: str = "wav"
    ) -> bytes:
        raise NotImplementedError


class OpenAIBackend(TranslationBackend):
    name = "OpenAI"

    def __init__(self):
        self.client: Optional[OpenAI] = None
        self._api_key: Optional[str] = None

    def translate(
        self, source_lang: str, target_lang: str, text: str, context_text: str = ""
    ) -> str:
        if not self.client:
            raise RuntimeError("OpenAI API key not configured.")

        source_desc = "auto-detect" if source_lang == "auto" else f"{source_lang}"
        context_block = ""
        if context_text.strip():
            context_block = f"\nContext: {context_text.strip()}\n"
        prompt = (
            "You are a high-accuracy translation engine.\n"
            "Rules:\n"
            "- Output ONLY the translated text.\n"
            "- Preserve meaning, tone, formatting, punctuation.\n"
            "- Do not add explanations.\n\n"
            f"Translate from {source_desc} to {target_lang}:{context_block}\n{text}"
        )

        # Responses API (recommended in current OpenAI docs)
        resp = self.client.responses.create(
            model=OPENAI_TRANSLATION_MODEL,
            input=prompt,
            temperature=0,
        )
        out = (getattr(resp, "output_text", None) or "").strip()
        return out

    def generate_info(
        self,
        kind: str,
        source_lang: str,
        target_lang: str,
        source_text: str,
        target_text: str,
        output_lang: str,
    ) -> str:
        if not self.client:
            raise RuntimeError("OpenAI API key not configured.")

        source_desc = "auto-detect" if source_lang == "auto" else f"{source_lang}"
        response_lang = output_lang or target_lang
        if kind == "examples":
            prompt = (
                "You are a helpful linguist.\n"
                "Task: Generate 3-5 example sentences in the target language.\n"
                "Rules:\n"
                "- Output only the sentences, one per line.\n"
                "- No numbering, bullets, or extra commentary.\n"
                "- Keep them concise and natural.\n\n"
                f"Source language: {source_desc}\n"
                f"Target language: {target_lang}\n"
                f"Respond in: {response_lang}\n"
                f"Source text: {source_text}\n"
                f"Translation: {target_text}"
            )
        elif kind == "alternatives":
            prompt = (
                "You are a high-accuracy translation assistant.\n"
                "Task: Provide 3 alternative translations.\n"
                "Rules:\n"
                "- Output only the alternatives, one per line.\n"
                "- No numbering, bullets, or extra commentary.\n"
                "- Preserve meaning and tone.\n\n"
                f"Source language: {source_desc}\n"
                f"Target language: {target_lang}\n"
                f"Respond in: {response_lang}\n"
                f"Source text: {source_text}\n"
                f"Current translation: {target_text}"
            )
        elif kind == "etymology":
            prompt = (
                "You are a linguist.\n"
                "Task: Provide a short etymology (1-2 sentences).\n"
                "Rules:\n"
                "- Output only the etymology text.\n"
                "- Keep it concise.\n\n"
                f"Respond in: {response_lang}\n"
                f"Word: {target_text}"
            )
        elif kind == "synonyms":
            prompt = (
                "You are a linguist.\n"
                "Task: Provide 5 synonyms based on the translated text.\n"
                "Rules:\n"
                "- Output only the synonyms, one per line.\n"
                "- No numbering, bullets, or extra commentary.\n"
                "- Match the part of speech and tone.\n\n"
                f"Respond in: {response_lang}\n"
                f"Text: {target_text}"
            )
        elif kind == "antonyms":
            prompt = (
                "You are a linguist.\n"
                "Task: Provide 5 antonyms based on the translated text.\n"
                "Rules:\n"
                "- Output only the antonyms, one per line.\n"
                "- No numbering, bullets, or extra commentary.\n"
                "- Match the part of speech and tone.\n\n"
                f"Respond in: {response_lang}\n"
                f"Text: {target_text}"
            )
        elif kind == "usage":
            prompt = (
                "You are a linguist.\n"
                "Task: Explain how, why, and when the translated phrase is used.\n"
                "Rules:\n"
                "- Output 2-3 concise sentences.\n"
                "- No bullet points.\n"
                "- Keep it practical for learners.\n\n"
                f"Respond in: {response_lang}\n"
                f"Text: {target_text}"
            )
        elif kind == "grammar":
            prompt = (
                "You are a linguist.\n"
                "Task: Provide a short grammar explanation for the translated text.\n"
                "Rules:\n"
                "- Output 2-3 concise sentences.\n"
                "- No bullet points.\n"
                "- Focus on grammar and structure, not vocabulary.\n\n"
                f"Respond in: {response_lang}\n"
                f"Text: {target_text}"
            )
        else:
            raise ValueError(f"Unknown info kind: {kind}")

        resp = self.client.responses.create(
            model=OPENAI_TRANSLATION_MODEL,
            input=prompt,
            temperature=0,
        )
        out = (getattr(resp, "output_text", None) or "").strip()
        return out

    def text_to_speech(
        self, text: str, voice: str = "alloy", response_format: str = "wav"
    ) -> bytes:
        if not self.client:
            raise RuntimeError("OpenAI API key not configured.")

        resp = self.client.audio.speech.create(
            model=OPENAI_TTS_MODEL,
            voice=voice,
            input=text,
            response_format=response_format,
        )
        content = getattr(resp, "content", None)
        if content is None and hasattr(resp, "read"):
            content = resp.read()
        if content is None:
            raise RuntimeError("No audio returned from TTS.")
        return content

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
