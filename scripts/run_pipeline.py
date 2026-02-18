"""パイプライン統合エントリポイント

@scout → @editor → @voice → @android の順に実行し、
毎日の AI ニュースエピソードを生成して docs/ に保存する。
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone

# リポジトリルートを sys.path に追加（GitHub Actions での実行対応）
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.scout import collect
from agents.editor import generate_script
from agents.voice import synthesize, get_audio_duration
from agents.android import update_feed


def run() -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    mp3_path = f"docs/episodes/{today}.mp3"

    print(f"=== AI News Podcast Pipeline: {today} ===")

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

    # @voice: 音声合成
    print("\n--- @voice: 音声合成中 ---")
    synthesize(script, mp3_path)

    # @android: RSS フィード更新
    print("\n--- @android: RSS 更新中 ---")
    duration_sec = get_audio_duration(mp3_path)
    update_feed(
        date_str=today,
        mp3_path=mp3_path,
        script=script,
        duration_sec=duration_sec,
    )

    print(f"\n=== 完了 ===")
    print(f"  MP3: {mp3_path}")
    print(f"  RSS: docs/feed.xml")


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
