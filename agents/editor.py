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



def generate_headline_and_body(articles: list["Article"], meta_path: str = "config/podcast_meta.yml") -> tuple[str, str]:
    """
    記事リストからPodcast台本のヘッドラインと本文を別々に生成して返す。
    Returns (headline, body)
    """
    meta = _load_meta(meta_path)
    model_id = meta.get("editor_model", "gemini-3-flash-preview")
    api_key = os.environ["GEMINI_API_KEY"]

    client = genai.Client(api_key=api_key)

    articles_text = "\n\n".join(
        f"【記事{i+1}】\nタイトル: {a.title}\nソース: {a.source}\n概要: {a.summary}"
        for i, a in enumerate(articles)
    )

    prompt = f"""あなたはAIニュース専門のラジオパーソナリティです。
以下のAI関連ニュース記事をもとに、日本語のポッドキャスト台本を生成してください。

【要件】
- **ヘッドライン**: 「おはようございます、AI ニュース Daily です」から始め、その日のニュースのヘッドラインを1〜2文で手短に紹介してください。
- **本文**: 各記事について、提供された概要をもとに、リスナーが内容を深く理解できるよう、背景情報や重要性を補足しながら、それぞれ300〜400字程度の詳細な解説を加えてください。記事から次の記事に移る際には、自然なつなぎの言葉を入れてください。最後にエンディングとして、情報源（メディア名）をまとめて紹介し、「本日のAIニュースは以上です。また明日お会いしましょう」で締めくくってください。
- **出力形式**: 以下のフォーマットで出力してください。
ヘッドライン:
（ここにヘッドライン）
本文:
（ここに本文）

【本日の記事】
{articles_text}
"""

    response = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=8192,
        ),
    )
    print(f"[editor] Raw script from API:\n---\n{response.text}\n---")
    script = response.text.strip()
    # ヘッドラインと本文を抽出
    headline = ""
    body = ""
    if script.startswith("ヘッドライン:"):
        parts = script.split("本文:", 1)
        if len(parts) == 2:
            headline = parts[0].replace("ヘッドライン:", "").strip()
            body = parts[1].strip()
        else:
            headline = script.strip()
    else:
        headline = script[:150].strip()
        body = script.strip()
    print(f"[editor] Headline: {headline[:80]}...")
    print(f"[editor] Body: {len(body)} chars")
    return headline, body


if __name__ == "__main__":
    from agents.scout import collect
    articles = collect()
    script = generate_script(articles)
    print(script)
