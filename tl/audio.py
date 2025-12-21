from __future__ import annotations

import io
import wave


def prepend_wav_silence(audio: bytes, seconds: float) -> bytes:
    if not audio or seconds <= 0:
        return audio
    if not (audio.startswith(b"RIFF") and b"WAVE" in audio[8:16]):
        return audio
    try:
        with wave.open(io.BytesIO(audio), "rb") as reader:
            params = reader.getparams()
            frames = reader.readframes(reader.getnframes())
    except Exception:
        return audio

    frame_rate = params.framerate
    sampwidth = params.sampwidth
    channels = params.nchannels
    if frame_rate <= 0 or sampwidth <= 0 or channels <= 0:
        return audio
    silence_frames = int(frame_rate * seconds)
    silence = b"\x00" * silence_frames * sampwidth * channels
    data_size = len(silence) + len(frames)
    if data_size > 4_000_000_000:
        return audio

    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(sampwidth)
        writer.setframerate(frame_rate)
        writer.writeframes(silence + frames)
    return out.getvalue()
