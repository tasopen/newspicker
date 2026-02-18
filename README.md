# newspicker — AI ニュース Podcast Generator

最新のAIニュースを毎朝自動収集・要約・音声化して、GitHub Pages 上で Podcast として配信するシステムです。

## 🏗 アーキテクチャ

```
毎朝 7:00 JST (GitHub Actions)
    │
    ├─ @scout    agents/scout.py   → NewsAPI + RSS → 上位5-8記事
    ├─ @editor   agents/editor.py  → Gemini 3 Flash → 日本語台本
    ├─ @voice    agents/voice.py   → Gemini TTS → MP3
    └─ @android  agents/android.py → Podcast RSS feed.xml 更新
                        │
                  GitHub Pages → AntennaPod (Android)
```

## 🔑 必要な Secrets

GitHub リポジトリの Settings → Secrets and variables → Actions に登録：

| 名前 | 取得元 |
|------|--------|
| `NEWS_API_KEY` | https://newsapi.org |
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey |

## ⚙️ セットアップ

1. このリポジトリを fork / clone
2. `config/podcast_meta.yml` の `base_url` を自分の GitHub Pages URL に変更
3. GitHub Secrets を設定
4. リポジトリの Settings → Pages → Source を `docs/` フォルダに設定
5. Actions タブから `daily_podcast.yml` を手動実行してテスト

## 📱 Android での購読

AntennaPod を開き、以下の URL を登録：
```
https://YOUR_USERNAME.github.io/newspicker/feed.xml
```

## 📦 依存関係・環境構築

[uv](https://docs.astral.sh/uv/) を使用します。

```bash
# uv のインストール（未導入の場合）
curl -LsSf https://astral.sh/uv/install.sh | sh  # macOS/Linux
# Windows: winget install astral-sh.uv

# 依存パッケージのインストール（仮想環境も自動作成）
uv sync

# スクリプト実行
uv run python scripts/run_pipeline.py
```

> ffmpeg も必要です（GitHub Actions の ubuntu-latest に標準搭載）。  
> ローカルでは `brew install ffmpeg` / `sudo apt install ffmpeg` / `winget install ffmpeg` 等でインストールしてください。
