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
        f"【記事{i+1}】\nタイトル: {a.title}\nソース: {a.source}\n概要: {a.summary}"
        for i, a in enumerate(articles)
    )

    prompt = f"""あなたはAIニュース専門のラジオパーソナリティです。
以下のAI関連ニュース記事をもとに、日本語のポッドキャスト台本を生成してください。

【要件】
- **構成**:
    1. **オープニング**: 「おはようございます、AI ニュース Daily です」から始め、その日のニュースのヘッドラインを1〜2文で手短に紹介します。
    2. **本編**: 各記事について、提供された概要をもとに、リスナーが内容を深く理解できるよう、背景情報や重要性を補足しながら、それぞれ300〜400字程度の詳細な解説を加えてください。記事から次の記事に移る際には、自然なつなぎの言葉を入れてください。
    3. **エンディング**: その日に取り上げた各ニュースの情報源（メディア名）をまとめて紹介し、「本日のAIニュースは以上です。また明日お会いしましょう」で締めくくります。（例：「本日のニュースは、〇〇、△△、□□などでお伝えしました。」）
- **スタイル**:
    - 自然で聴きやすい、プロのアナウンサーのような話し言葉を心がけてください。
    - 記事のURLや専門用語は、一般的なリスナーにも分かりやすいように、読みやすい日本語に変換してください。（例: `https://example.com` は「公式サイト」と表現する）
- **長さ**:
    - 全体で最低でも1500文字以上（読み上げ時間6分以上）になるように、各ニュースの詳細な解説を含めてください。
- **出力形式**:
    - 台本テキストのみを出力し、説明や注釈は一切含めないでください。

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
    # APIからの生レスポンスをログ出力
    print(f"[editor] Raw script from API:\n---\n{response.text}\n---")
    script = response.text.strip()
    print(f"[editor] Script generated: {len(script)} chars")
    return script


if __name__ == "__main__":
    from agents.scout import collect
    articles = collect()
    script = generate_script(articles)
    print(script)
