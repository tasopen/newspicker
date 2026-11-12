# newspicker — 多言語 RSS Podcast Generator

複数の言語からなる最新のニュース（AI、技術、自動車など）を RSS から自動収集・日本語で要約・音声化して、GitHub Pages 上で Podcast として配信するシステムです。RSS と Gemini Grounding Search を活用した自動メンテナンス機能を備えています。

サンプルとして AI 関連のニュースを集めた Podcast、[朝刊ワールドAIニュース](https://tasopen.github.io/newspicker/index.html) を公開しています：

## 🏗 アーキテクチャ

```
毎朝 5:17 JST
    │
    ├─ cron-job.org ──→ workflow_dispatch（正確な時刻で起動）
    └─ GitHub cron  ──→ schedule '17 20 * * *'（遅延するが保険として残す）
    │
    ├─ 同日エピソード存在チェック（feed.xml を grep）
    │     既にあれば全ステップを skip（二重生成を防止）
    │
    ├─ @scout    agents/scout.py   → 多言語 RSS (日・中・英) → 上位 7 記事
    │                                 [timing] ログ
    │
    ├─ @editor   agents/editor.py  → Gemini 3 Flash → カテゴリ別・動的台本生成
    │                                 API timeout: 120s / retry: max 3
    │                                 [timing] / [editor] ログ
    │
    ├─ @voice    agents/voice.py   → Gemini TTS → MP3 & SRT (字幕)
    │                                 API timeout: 120s / retry: max 3
    │                                 segment単位の [timing] / [voice] ログ
    │
    ├─ @android  agents/android.py → Podcast RSS (feed.xml) 更新
    │                                 [timing] ログ
    │
    └─ archive_episode.py → MP3/SRT を GitHub Releases へ退避
                            → feed.xml の URL 差し替え → コミット
                       │
毎週日曜 12:00 JST
    └─ @maintenance scripts/maintain_feeds.py → Gemini Grounding Search
                                             → 生存確認・URL復旧・新規発見
```

### スケジュール遅延への対策

GitHub Actions の `schedule` イベントは、負荷が高い時間帯（特に毎時 0 分）に大幅に遅延します。実測では `0 19 * * *`（04:00 JST）の予定が **139〜414 分遅れ**（平均 235 分）で起動していました。

対策として二段構えにしています。

1. **cron-job.org から `workflow_dispatch` を叩く**（主系・時刻が正確）
2. **GitHub cron を `17 20 * * *`（05:17 JST）で残す**（副系・毎時 0 分を回避）

両方が発火しても、`concurrency: daily-podcast` による直列化と同日チェックで **1 日 1 エピソード**に収まります。

## ⚙️ 独自の内容に変える手順

このテンプレートは、設定ファイルを書き換えるだけで別ジャンルの Podcast に流用できます。新しいテーマで使うときは、以下の順で変更すると手戻りが少なくなります。

1. **配信名と公開URLを決める**
   - GitHub リポジトリ名を変える場合は、この段階で変更
   - `config/podcast_meta.yml` の `base_url` を `https://<GitHubユーザー名>.github.io/<リポジトリ名>` に更新
   - `scripts/publish_to_github.py` は現在の Git 情報から owner/repo を自動判定するので、通常は追加修正不要
2. **番組メタ情報を変える**
   - `config/podcast_meta.yml` の `title`, `short_title`, `description`, `author`, `category` を更新
   - Apple Podcasts / Spotify 向けに `name` と `email` を設定すると、RSS に `itunes:owner` と `atom:link rel="self"` が入る
   - `prompt_persona`, `prompt_greeting` を新テーマ向けの語り口に合わせる
   - 配信先URLが変わったら、既存の `docs/feed.xml` と `docs/index.html` は再生成される前提で扱う
3. **ニュースソースを入れ替える**
   - `config/sources.yml` の `keywords` を対象テーマ向けに変更
   - `rss_feeds` を収集したい媒体に入れ替える
4. **見た目を差し替える**
   - `docs/podcast_cover.jpg` を新しいカバー画像に差し替える
   - 推奨サイズは 1400x1400px、500KB 以下
5. **動作確認する**
   - `uv run python scripts/run_pipeline.py` を実行
   - 生成された `docs/feed.xml` と `docs/index.html` を確認
   - 問題なければ GitHub Pages と Podcast アプリで購読テスト

補足:
- `pyproject.toml` の `name` は Python プロジェクト名です。リポジトリ名と一致していなくても動作はしますが、配布名や環境表示も揃えたい場合は変更してください。
- `pyproject.toml` の `name` を変えた場合は `uv sync` または `uv lock` をやり直すのが安全です。

## 🔑 必要な Secrets

GitHub リポジトリの Settings → Secrets and variables → Actions に登録：

| 名前 | 必須 | 取得元 | 役割 |
|------|------|--------|------|
| `GEMINI_API_KEY` | ✅ | [Google AI Studio](https://aistudio.google.com/apikey) | 台本生成, 音声合成, Grounding Search |
| `IA_ACCESS_KEY` | 任意 | [archive.org S3 Keys](https://archive.org/account/s3.php) | archive.org への複製（`archive.internet_archive: true` のときのみ） |
| `IA_SECRET_KEY` | 任意 | 同上（Generate New Keys で同時に発行） | 同上 |

`GITHUB_TOKEN` は Actions が自動で提供するため登録不要です。

`IA_ACCESS_KEY` / `IA_SECRET_KEY` は **任意** です。未登録でも `archive.internet_archive` が `false`（既定）なら何も起きず、ジョブも失敗しません。

### ローカル実行用の `.env`

`scripts/mirror_to_archive_org.py` などローカルから実行するスクリプトは `.env` を自動で読み込みます（`python-dotenv` 不要）。`.env` は `.gitignore` 済みです。

```
IA_ACCESS_KEY=xxxxxxxx
IA_SECRET_KEY=xxxxxxxx
```

### cron-job.org 用の Personal Access Token

外部 cron から `workflow_dispatch` を叩くため、GitHub の PAT を発行して cron-job.org に登録します（Actions の Secrets ではありません）。

- **Fine-grained token**: Repository access で `tasopen/newspicker` を選択 → Permissions → **Actions: Read and write**
- **Classic token**: scope で **`workflow`** にチェック

有効期限を設定し（例: 1 年）、期限切れ前に更新してください。

## ⚙️ セットアップ

1. このリポジトリを fork / clone
2. `config/podcast_meta.yml` の `base_url` を自分の GitHub Pages URL に変更
3. GitHub Secrets に `GEMINI_API_KEY` を設定（`IA_ACCESS_KEY` / `IA_SECRET_KEY` は任意）
4. リポジトリの Settings → Pages → Source を `docs/` フォルダに設定
5. Actions タブから `daily_podcast.yml` を手動実行してテスト
6. （推奨）cron-job.org で毎朝 5:17 JST に起動するジョブを登録

### cron-job.org の設定

| 項目 | 値 |
|------|-----|
| URL | `https://api.github.com/repos/<owner>/<repo>/actions/workflows/daily_podcast.yml/dispatches` |
| Method | `POST` |
| Schedule | 毎日 05:17（Timezone: `Asia/Tokyo`） |
| Headers | `Authorization: Bearer <PAT>`<br>`Accept: application/vnd.github+json`<br>`Content-Type: application/json`<br>`User-Agent: cron-job.org` |
| Body | `{"ref":"master"}` |
| Timeout | 30 秒（API は即座に `204 No Content` を返す） |

成功時は `204 No Content` が返ります。ワークフローの完了は待たないため、30 秒で十分です。

curl で書くと以下のとおりです。

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GITHUB_PAT" \
  -H "Content-Type: application/json" \
  -H "User-Agent: cron-job.org" \
  -d '{"ref":"master"}' \
  -m 30 \
  https://api.github.com/repos/<owner>/<repo>/actions/workflows/daily_podcast.yml/dispatches
```

## 💾 音声アーカイブ（Pages 容量対策）

GitHub Pages には **公開サイト 1 GB** の上限があります。音声を `docs/episodes/` に置き続けると必ず超過するため、`scripts/archive_episode.py` で MP3/SRT の実体を外部へ退避します。

- **主系**: GitHub Releases（`episodes-YYYY-MM` タグ、無料・容量無制限）— 常に有効
- **副系（任意）**: archive.org（`newspicker-tasopen-YYYY-MM` アイテム、恒久保存）

archive.org への複製は**サービス依存の任意機能**です。`config/podcast_meta.yml` で有効化します。

```yaml
archive:
  github_releases: true    # 既定 true（無料・容量無制限）
  internet_archive: false  # 既定 false。true にする場合は IA_ACCESS_KEY / IA_SECRET_KEY も必要
```

`internet_archive: false`（既定）のままなら、キー未設定でも警告を出してスキップするだけで**ジョブは失敗しません**。フォークして毎日赤くなることはありません。

> **配信元は常に GitHub Releases** です。archive.org は SLA も帯域も保証がないため、`feed.xml` の enclosure には使いません（`--primary archive` は廃止）。

`feed.xml` の `<enclosure>` と `<link>` は退避先 URL に書き換わりますが、**`<guid>` は変更しません**。購読者は同じエピソードのまま新 URL から取得できます。

```bash
# 最新エピソードのみ退避（日次ワークフローが自動実行）
uv run python scripts/archive_episode.py --latest --delete-local --allow-partial

# 既存分を一括移行（Actions の migrate_episodes.yml から実行）
uv run python scripts/archive_episode.py --all --delete-local --allow-partial

# 対象の確認だけ
uv run python scripts/archive_episode.py --all --dry-run
```

### `--allow-partial` について

archive.org は非常に遅く（実測 約 0.4 MB/s、GitHub Releases は約 5 MB/s）、タイムアウトも発生します。`--allow-partial` を付けると、**一部が失敗しても続行し、URL が確定したファイルだけ削除**します。未退避の実体は Pages 配信を継続するため、enclosure が壊れません。

付けない場合、1 ファイルでも失敗すると終了コード 1 になり、削除もコミットも行われません（過去にこれが原因で Pages が 1.24 GB まで肥大し、デプロイがタイムアウトしました）。

### 一括移行ワークフロー（`migrate_episodes.yml`）

Actions から手動実行します。入力パラメータは以下のとおりです。

| 入力 | 既定 | 説明 |
|------|------|------|
| `dry_run` | `true` | アップロードせず対象だけ表示 |
| `delete_local` | `false` | 退避後に `docs/episodes` の実体を削除 |
| `internet_archive` | `false` | archive.org にも複製する（非常に遅い） |

`internet_archive: false`（既定）なら GitHub Releases のみに退避するため、**54 分 → 約 1 分**に短縮されます。archive.org への複製は後からローカルで `mirror_to_archive_org.py` を実行してください。

コミットステップは `always()` で実行されるため、部分成功でも `feed.xml` の書き換えと実体削除が反映されます。

### archive.org への複製（ローカル実行用）

移行後は MP3 の実体が GitHub Releases にしかないため、`archive_episode.py` はそのままでは動きません。`scripts/mirror_to_archive_org.py` が Release からダウンロードして archive.org へ複製します。

```bash
# 不足分の確認だけ
uv run python scripts/mirror_to_archive_org.py --dry-run

# 不足分をすべて複製（冪等：既にあるファイルはスキップ）
uv run python scripts/mirror_to_archive_org.py

# 特定の月だけ
uv run python scripts/mirror_to_archive_org.py --month 2026-03
```

ファイル単位で進捗・経過時間・残り時間（ETA）を表示します。

```
[mirror]   up 34/49 2026-03-24_061110.mp3 (12.6s) | total 34/49 (69%) elapsed 3m27s ETA 1m31s
```

> **注意 1**: archive.org の metadata API（`/metadata/<id>`）は反映が非常に遅く、実際には配信されているファイルを「無い」と返すことがあります。検証は `/download/<id>/<name>` への HEAD リクエストで行ってください。
>
> **注意 2**: archive.org はアップロード成功を返してもファイルを落とすことがあります。アップロード後は必ず配信を確認してください。
>
> **注意 3**: 過去の MP3 を `git rm` しても `.git` のサイズは減りません。履歴から完全に消すには `git filter-repo` が必要です。

## 🛠 フィード自動メンテナンス

`scripts/maintain_feeds.py` は以下の機能を提供します：
- **生存確認**: 応答がないフィードを検知（3回連続で自動削除）
- **自動修復**: URL が変わった場合、Gemini Grounding Search で新しいアドレスを検索・更新
- **自動発見**: 人気の RSS フィードを Grounding Search で定期的に検索し、リストに追加

## ✍️ エディタープロンプトの使い方

台本生成は、[config/podcast_meta.yml](config/podcast_meta.yml) の `editor_prompt_template` で定義したプロンプトをもとに行います。`agents/editor.py` では、このテンプレートが見つからない場合に備えてフォールバック用の既定プロンプトを持っています。

- 主要な調整ポイントは `persona`、`greeting`、`tts_model`、`short_title` などです。
- 文章のトーン、見出しの長さ、ふりがなルール、記事の並び順などは、このテンプレート内で制御できます。
- 新しいテーマに切り替えるときは、まず `editor_prompt_template` を編集して、読み上げ方針や用語ルールを合わせるのがおすすめです。
- ふりがなについては、括弧は読みのためだけに使い、括弧内はひらがな・カタカナの単純な読みのみとするルールを明示すると、音声化時のノイズを減らせます。

## 📱 アプリでの購読

Podcast アプリ（AntennaPod, Apple Podcasts 等）を開き、以下の URL を登録：
```
https://<あなたのユーザー名>.github.io/<あなたのリポジトリ名>/feed.xml
```

## 📦 依存関係・環境構築

[uv](https://docs.astral.sh/uv/) を使用します。

```bash
# 依存パッケージのインストール
uv sync

# パイプラインの手動実行
uv run python scripts/run_pipeline.py

# フィードメンテナンスの手動実行
uv run python scripts/maintain_feeds.py --auto-add
```

## 🛠 開発とデバッグ

### デバッグモードの利用
パイプライン実行時に `--debug` フラグを付けることで、デバッグ情報が出力され、中間データが保存されます。

```bash
uv run python scripts/run_pipeline.py --debug
```

- **PCMデータの保存**: `docs/episodes/` 内に、TTSから返された生の音声データ (`.pcm`) が保存されます。音声品質の確認に利用できます。
- **詳細なエラーログ**: APIレスポンスの詳細（finish_reason や安全しきい値の状態など）が出力されます。

### 最近の改善点
- **スケジュール遅延対策**: GitHub の `schedule` は毎時 0 分に大幅に遅延するため、cron-job.org からの `workflow_dispatch` を主系に、GitHub cron を `17 20 * * *`（05:17 JST）の保険として併用。`concurrency` と同日チェックで二重生成を防止。
- **Pages 容量対策の完成**: `--allow-partial` により部分成功でも削除・コミットを続行。`migrate_episodes.yml` に `internet_archive` 入力を追加（既定 `false`）し、遅い archive.org を外して一括移行を 54 分 → 1 分に短縮。
- **archive.org をオプション化**: `config/podcast_meta.yml` の `archive.internet_archive`（既定 `false`）で制御。キー未設定でも警告のみでスキップし、フォークしてもジョブが失敗しない。`--primary archive` は廃止（配信元は常に GitHub Releases）。
- **archive.org バックフィル**: `scripts/mirror_to_archive_org.py` で Release から不足分を複製。153 ファイルを約 15 分で処理し、全 532 ファイルの配信を確認済み。
- **パイプライン安定化 (3段階防御)**:
  - **実行時間ログ**: 全セクション（@scout, @editor, @voice, @android）とVoice各segmentの実行時間を `[timing]` / `[voice]` ログで出力。どこで時間を消費しているか特定可能。
  - **GitHub Actions タイムアウト**: `Run pipeline` ステップに `timeout-minutes: 60` を設定。長時間のハングを防止。
  - **API タイムアウト・リトライ**: Gemini API 呼び出しに120秒のタイムアウトと最大3回のリトライ（指数バックオフ+jitter）を実装。一時的なAPI障害を自動回復。恒久的エラー（400系）は即時失敗。
- エディタープロンプトでは、括弧はふりがな表示にのみ使用し、括弧内はひらがな・カタカナの単純な読みだけにするルールを明示しました。
- 音声合成前のテキスト整形では、1文に複数の括弧付き表記があっても、前後の文脈を巻き込まずに各ふりがなを処理するようにしました。

### 便利な環境変数
ローカルでの開発・テスト時に以下の環境変数を設定することで、動作をカスタマイズできます。

- `GEMINI_API_KEY`: 必須。
- `TEST_OUTPUT_PATH`: 出力先（通常は `docs/`）を一時的に別の場所に変更したい場合に使用します。

> ffmpeg が必要です。GitHub Actions には標準搭載されています。
