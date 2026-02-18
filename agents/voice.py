"""@voice: 音声合成エージェント

Gemini TTS (gemini-2.5-flash-preview-tts) を使って台本テキストを MP3 に変換する。
出力フォーマット: PCM → WAV → MP3 (pydub + ffmpeg)
"""
from __future__ import annotations

import io
import os
import wave

import yaml
from google import genai
from google.genai import types
from pydub import AudioSegment


def _load_meta(meta_path: str = "config/podcast_meta.yml") -> dict:
    with open(meta_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _pcm_to_wav_bytes(pcm_data: bytes, channels: int = 1, rate: int = 24000, sample_width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def synthesize(script: str, output_path: str, meta_path: str = "config/podcast_meta.yml") -> str:
    """台本テキストを音声合成して MP3 ファイルに保存する。output_path を返す。"""
    meta = _load_meta(meta_path)
    tts_model = meta.get("tts_model", "gemini-2.5-flash-preview-tts")
    voice_name = meta.get("voice", "Kore")
    api_key = os.environ["GEMINI_API_KEY"]

    client = genai.Client(api_key=api_key)

    # Gemini TTS はテキストをそのまま読み上げるので、
    # プロンプトで読み上げスタイルを指示する
    tts_prompt = f"ラジオパーソナリティのトーンで、落ち着いてはっきりと日本語で読み上げてください:\n\n{script}"

    response = client.models.generate_content(
        model=tts_model,
        contents=tts_prompt,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name,
                    )
                )
            ),
        ),
    )

    # PCM バイナリを取得
    pcm_data = response.candidates[0].content.parts[0].inline_data.data

    # PCM → WAV → MP3
    wav_bytes = _pcm_to_wav_bytes(pcm_data)
    audio = AudioSegment.from_wav(io.BytesIO(wav_bytes))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    audio.export(output_path, format="mp3", bitrate="128k")

    size_kb = os.path.getsize(output_path) // 1024
    duration_sec = int(len(audio) / 1000)
    print(f"[voice] Saved {output_path} ({size_kb} KB, {duration_sec}s)")
    return output_path


def get_audio_duration(mp3_path: str) -> int:
    """MP3 ファイルの長さを秒で返す。"""
    audio = AudioSegment.from_mp3(mp3_path)
    return int(len(audio) / 1000)


if __name__ == "__main__":
    import sys
    script = sys.argv[1] if len(sys.argv) > 1 else "こんにちは、テストです。"
    synthesize(script, "docs/episodes/test.mp3")
