"""パイプライン統合エントリポイント

@scout → @editor → @voice → @android の順に実行し、
毎日の AI ニュースエピソードを生成して docs/ に保存する。
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone
import re

# リポジトリルートを sys.path に追加（GitHub Actions での実行対応）
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.scout import collect, save_seen_urls
from agents.editor import generate_script
from agents.voice import synthesize, get_audio_duration
from agents.android import update_feed


def _format_srt_time(ms: int) -> str:
    h = ms // 3600000
    ms_rem = ms % 3600000
    m = ms_rem // 60000
    s = (ms_rem % 60000) // 1000
    ms_part = ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms_part:03d}"


def _write_srt(script: str, duration_sec: int, srt_path: str) -> None:
    os.makedirs(os.path.dirname(srt_path), exist_ok=True)
    # 簡易的に文章を句点で分割して均等割り当てする
    segments = [s.strip() for s in re.split(r'(?<=[。！？\!\?])\s*', script) if s.strip()]
    if not segments:
        segments = [script.strip()]
    total_ms = int(duration_sec * 1000)
    per_ms = max(1, total_ms // len(segments))
    parts: list[str] = []
    for i, seg in enumerate(segments):
        start_ms = i * per_ms
        end_ms = (i + 1) * per_ms - 1 if i < len(segments) - 1 else total_ms
        start = _format_srt_time(start_ms)
        end = _format_srt_time(end_ms)
        parts.append(f"{i+1}\n{start} --> {end}\n{seg}\n")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    print(f"[voice] Saved SRT {srt_path}")


def run() -> None:
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d %H:%M:%S")
    timestamp = now.strftime("%Y-%m-%d_%H%M%S")
    mp3_path = f"docs/episodes/{timestamp}.mp3"
    wav_path = f"docs/episodes/{timestamp}.wav"

    # コマンドライン引数で--debugを受け付ける
    debug = getattr(run, "debug", False)

    print(f"=== AI News Podcast Pipeline: {date_str} ===")

    # @scout: ニュース収集
    print("\n--- @scout: 収集中 ---")
    articles = collect()
    if not articles:
        print("[pipeline] 記事が見つかりませんでした。終了します。")
        sys.exit(1)

    # @editor: 台本生成
    print("\n--- @editor: 台本生成中 ---")
    script = generate_script(articles)
    if not script:
        print("[pipeline] 台本生成に失敗しました。終了します。")
        sys.exit(1)


    # @voice: 音声合成（2分ごとに分割生成＆結合）
    print("\n--- @voice: 音声合成中 ---")
    # 2分=120秒, Gemini TTSは24kHz/16bit/monoなので1秒=48000byte程度
    # 句点・改行で分割し、各セグメントの合計文字数で近似的に2分ごとに分割
    import re
    from agents.voice_concat import concat_wav
    # 分割バッファを約1000文字に変更
    max_chars = 1000
    # 句点・改行で分割
    segments = [s.strip() for s in re.split(r'[。！？\!\?\n]', script) if s.strip()]
    seg_groups = []
    buf = ""
    for seg in segments:
        if len(buf) + len(seg) > max_chars and buf:
            seg_groups.append(buf)
            buf = seg
        else:
            buf += ("。" if buf else "") + seg
    if buf:
        seg_groups.append(buf)
    wav_parts = []
    for i, seg in enumerate(seg_groups):
        part_path = wav_path.replace('.wav', f'_part{i+1}.wav')
        print(f"  [voice] {i+1}/{len(seg_groups)}: {len(seg)} chars")
        # synthesizeでWAV出力
        synthesize(seg, part_path, debug=debug, output_format="wav")
        wav_parts.append(part_path)
    if len(wav_parts) == 1:
        os.rename(wav_parts[0], wav_path)
    else:
        concat_wav(wav_parts, wav_path)
        for p in wav_parts:
            os.remove(p)
    # WAV→MP3変換
    from agents.voice import _convert_wav_to_mp3
    with open(wav_path, "rb") as f:
        wav_bytes = f.read()
    _convert_wav_to_mp3(wav_bytes, mp3_path)
    os.remove(wav_path)

    # @android: RSS フィード更新
    print("\n--- @android: RSS 更新中 ---")
    duration_sec = get_audio_duration(mp3_path)
    srt_path = mp3_path.replace('.mp3', '.srt')
    _write_srt(script, duration_sec, srt_path)
    # feed.xml出力先を環境変数で切り替え
    feed_path = os.environ.get("FEED_XML_PATH", "docs/feed.xml")
    update_feed(
        date_str=date_str,
        mp3_path=mp3_path,
        srt_path=srt_path,
        script=script,
        duration_sec=duration_sec,
        feed_path=feed_path,
    )

    # 使用済み URL を記録（次回以降の重複排除）
    save_seen_urls([a.url for a in articles])

    print(f"\n=== 完了 ===")
    print(f"  MP3: {mp3_path}")
    print(f"  RSS: docs/feed.xml")


if __name__ == "__main__":
    debug = "--debug" in sys.argv
    setattr(run, "debug", debug)
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
