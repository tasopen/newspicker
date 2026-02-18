"""@editor: 台本生成エージェント

収集記事リストを受け取り、Gemini 3 Flash でラジオ台本（日本語）を生成する。
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import yaml
from google import genai
from google.genai import types

if TYPE_CHECKING:
    from agents.scout import Article


def _load_meta(meta_path: str = "config/podcast_meta.yml") -> dict:
    with open(meta_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def generate_script(articles: list["Article"], meta_path: str = "config/podcast_meta.yml") -> str:
    """記事リストからPodcast台本テキストを生成して返す。"""
    meta = _load_meta(meta_path)
    model_id = meta.get("editor_model", "gemini-3-flash-preview")
    api_key = os.environ["GEMINI_API_KEY"]

    client = genai.Client(api_key=api_key)

    # 記事サマリーを構築
    articles_text = "\n\n".join(
        f"【記事{i+1}】\nタイトル: {a.title}\nソース: {a.source}\n概要: {a.summary[:400]}"
        for i, a in enumerate(articles)
    )

    prompt = f"""あなたはAIニュース専門のラジオパーソナリティです。
以下のAI関連ニュース記事をもとに、日本語のポッドキャスト台本を生成してください。

【要件】
- 自然で聴きやすい話し言葉のスタイル
- 各トピックを1〜2文で簡潔に紹介
- 全体で750〜1200文字（読み上げ時間3〜5分相当）
- 冒頭に「おはようございます、AI ニュース Daily です」から始める
- 末尾に「本日のAIニュースは以上です。また明日お会いしましょう」で締める
- 記事のURLや英語の技術用語は読みやすい日本語に変換する
- 台本テキストのみ出力し、説明や注釈は不要

【本日の記事】
{articles_text}
"""

    response = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=2048,
        ),
    )
    script = response.text.strip()
    print(f"[editor] Script generated: {len(script)} chars")
    return script


if __name__ == "__main__":
    from agents.scout import collect
    articles = collect()
    script = generate_script(articles)
    print(script)
