#!/usr/bin/env python3
"""エピソード音声を GitHub Releases / archive.org へ退避し、feed.xml の URL を差し替える。

GitHub Pages の 1 GB 上限を回避するため、MP3/SRT の実体を Pages から追い出す。
`guid` は変更しないので、購読者は同じエピソードのまま新 URL から取得できる。

使い方:
  # 最新エピソードだけ退避（Actions の日次実行用）
  python scripts/archive_episode.py --latest

  # 既存の全エピソードを一括移行
  python scripts/archive_episode.py --all

  # 何が起きるかだけ確認
  python scripts/archive_episode.py --all --dry-run

必要な環境変数:
  GITHUB_TOKEN     GitHub Releases へのアップロード（Actions では secrets.GITHUB_TOKEN）

任意の環境変数:
  GITHUB_REPOSITORY   既定: tasopen/newspicker
  IA_ITEM_PREFIX      既定: newspicker-tasopen
  IA_ACCESS_KEY       archive.org の S3 アクセスキー（internet_archive 有効時のみ）
  IA_SECRET_KEY       archive.org の S3 シークレットキー（同上）
  ARCHIVE_SKIP_GITHUB 1 で GitHub Releases へのアップロードを省略
  ARCHIVE_SKIP_IA     1 で archive.org へのアップロードを省略

archive.org への退避は `config/podcast_meta.yml` の
`archive.internet_archive` で有効化する（既定: false）。
キーが未設定なら警告を出して自動的にスキップするため、
フォークしてもジョブは失敗しない。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from urllib.parse import quote

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.android import (  # noqa: E402
    ATOM_NS,
    CONTENT_NS,
    ITUNES_NS,
    PODCAST_NS,
    _load_meta,
)

from xml.etree import ElementTree as ET  # noqa: E402

ET.register_namespace("itunes", ITUNES_NS)
ET.register_namespace("atom", ATOM_NS)
ET.register_namespace("content", CONTENT_NS)
ET.register_namespace("podcast", PODCAST_NS)

DEFAULT_REPO = "tasopen/newspicker"
DEFAULT_IA_PREFIX = "newspicker-tasopen"
RELEASE_TAG_PREFIX = "episodes-"
EPISODES_DIR = "docs/episodes"
FEED_PATH = "docs/feed.xml"

GH_API = "https://api.github.com"


def log(msg: str) -> None:
    """Actions のログに即時反映させる（stdout はパイプだとブロックバッファされる）。"""
    print(msg, flush=True)


# --------------------------------------------------------------------------
# GitHub Releases
# --------------------------------------------------------------------------
def _gh_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def ensure_release(tag: str, token: str, repo: str) -> dict:
    """指定タグのリリースを取得する。無ければ作成する。"""
    headers = _gh_headers(token)
    r = requests.get(f"{GH_API}/repos/{repo}/releases/tags/{tag}", headers=headers, timeout=30)
    if r.status_code == 200:
        return r.json()
    if r.status_code != 404:
        r.raise_for_status()

    month = tag.removeprefix(RELEASE_TAG_PREFIX)
    r = requests.post(
        f"{GH_API}/repos/{repo}/releases",
        headers=headers,
        json={
            "tag_name": tag,
            "name": f"Episodes {month}",
            "body": (
                f"{month} のエピソード音声アーカイブ。\n\n"
                "GitHub Pages の容量上限を避けるため、音声実体はここに置いています。"
            ),
            "draft": False,
            "prerelease": False,
        },
        timeout=30,
    )
    r.raise_for_status()
    log(f"[archive] created release {tag}")
    return r.json()


def upload_release_asset(release: dict, path: str, token: str) -> str:
    """リリースにファイルを添付し、ダウンロード URL を返す。既存なら再利用する。"""
    name = os.path.basename(path)
    for asset in release.get("assets", []):
        if asset.get("name") == name:
            log(f"[archive] release asset already exists: {name}")
            return asset["browser_download_url"]

    upload_url = release["upload_url"].split("{", 1)[0]
    with open(path, "rb") as f:
        payload = f.read()

    r = requests.post(
        f"{upload_url}?name={quote(name)}",
        headers={**_gh_headers(token), "Content-Type": "application/octet-stream"},
        data=payload,
        timeout=600,
    )
    r.raise_for_status()
    url = r.json()["browser_download_url"]
    log(f"[archive] uploaded to release: {name} ({len(payload) / 1e6:.2f} MB)")
    return url


# --------------------------------------------------------------------------
# archive.org
# --------------------------------------------------------------------------
def upload_to_archive(paths: list[str], identifier: str, access: str, secret: str) -> None:
    """archive.org のアイテムへアップロードする（既存ファイルは上書き）。"""
    from internetarchive import upload

    metadata = {
        "title": f"朝刊ワールドAIニュース {identifier.rsplit('-', 1)[-1]}",
        "mediatype": "audio",
        "collection": "opensource_audio",
        "creator": "TasogarePenguin",
        "language": "jpn",
        "subject": "podcast; AI news; ポッドキャスト",
        "description": "AI ニュースのポッドキャスト音声アーカイブ。",
    }
    responses = upload(
        identifier,
        files=paths,
        metadata=metadata,
        access_key=access,
        secret_key=secret,
        queue_derive=False,  # 派生ファイル生成を止めて時間と容量を節約
        retries=3,
        verbose=True,
    )
    for resp in responses:
        status = getattr(resp, "status_code", None)
        if status is not None and status >= 400:
            raise RuntimeError(f"archive.org upload failed ({status}): {resp.text[:300]}")
    log(f"[archive] uploaded {len(paths)} file(s) to archive.org item {identifier}")


def archive_url(identifier: str, filename: str) -> str:
    return f"https://archive.org/download/{identifier}/{quote(filename)}"


# --------------------------------------------------------------------------
# 設定（config/podcast_meta.yml の archive セクション）
# --------------------------------------------------------------------------
def load_archive_config(meta_path: str = "config/podcast_meta.yml") -> dict:
    """archive セクションを読む。無ければ空 dict（＝既定値を使う）。"""
    try:
        meta = _load_meta(meta_path)
    except Exception as exc:  # noqa: BLE001
        log(f"[archive] WARNING: cannot read {meta_path}: {exc}")
        return {}
    section = (meta or {}).get("archive") or {}
    return section if isinstance(section, dict) else {}


# --------------------------------------------------------------------------
# feed.xml の URL 差し替え
# --------------------------------------------------------------------------
def rewrite_feed(feed_path: str, url_map: dict[str, str], dry_run: bool = False) -> int:
    """feed.xml の enclosure / transcript URL を url_map に従って差し替える。

    guid と link は変更しない（購読者の同一性を保つため）。
    """
    tree = ET.parse(feed_path)
    root = tree.getroot()
    changed = 0

    for item in root.iter("item"):
        enclosure = item.find("enclosure")
        if enclosure is not None:
            old = enclosure.get("url", "")
            new = url_map.get(os.path.basename(old))
            if new and new != old:
                enclosure.set("url", new)
                changed += 1

        # <link> も実体を指すようにする（<guid> は購読者の同一性のため変更しない）
        link = item.find("link")
        if link is not None and link.text:
            new = url_map.get(os.path.basename(link.text))
            if new and new != link.text:
                link.text = new
                changed += 1

        for transcript in item.findall(f"{{{PODCAST_NS}}}transcript"):
            old = transcript.get("url", "")
            new = url_map.get(os.path.basename(old))
            if new and new != old:
                transcript.set("url", new)
                changed += 1

    if changed and not dry_run:
        ET.indent(tree, space="  ")
        with open(feed_path, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            tree.write(f, encoding="unicode", xml_declaration=False)
        log(f"[archive] feed.xml updated: {changed} URL(s) rewritten")
        _regenerate_index(feed_path, root)
    elif changed:
        log(f"[archive] (dry-run) would rewrite {changed} URL(s) in feed.xml")
    else:
        log("[archive] feed.xml already up to date")
    return changed


def _regenerate_index(feed_path: str, root: ET.Element) -> None:
    """index.html の再生リンクも新しい URL に合わせて作り直す。"""
    from agents.android import (
        _build_podcast,
        _extract_episodes,
        _load_meta,
        generate_index_html,
        _write_index_html,
    )

    channel = root.find("channel")
    if channel is None:
        return
    try:
        meta = _load_meta()
        base_url = meta["base_url"].rstrip("/")
        podcast = _build_podcast(meta, base_url)
        episodes = _extract_episodes(channel)
        html = generate_index_html(podcast, episodes)
        index_path = os.path.join(os.path.dirname(feed_path), "index.html")
        _write_index_html(html, index_path)
        log(f"[archive] index.html regenerated -> {index_path}")
    except Exception as exc:  # noqa: BLE001
        log(f"[archive] index.html regeneration skipped: {exc}")


# --------------------------------------------------------------------------
# 対象エピソードの収集
# --------------------------------------------------------------------------
def _episode_files(mp3_path: str) -> list[str]:
    files = [mp3_path]
    srt = mp3_path[:-4] + ".srt"
    if os.path.exists(srt):
        files.append(srt)
    return files


def _month_tag(mp3_path: str) -> str:
    """2026-11-07_084127.mp3 -> episodes-2026-11"""
    return RELEASE_TAG_PREFIX + os.path.basename(mp3_path)[:7]


def collect_targets(all_episodes: bool) -> list[str]:
    if not os.path.isdir(EPISODES_DIR):
        raise SystemExit(f"episodes directory not found: {EPISODES_DIR}")
    mp3s = sorted(
        os.path.join(EPISODES_DIR, n)
        for n in os.listdir(EPISODES_DIR)
        if n.endswith(".mp3")
    )
    if not mp3s:
        raise SystemExit("no mp3 files found")
    return mp3s if all_episodes else mp3s[-1:]


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--latest", action="store_true", help="最新エピソードのみ退避")
    group.add_argument("--all", action="store_true", help="既存の全エピソードを一括移行")
    parser.add_argument("--dry-run", action="store_true", help="アップロードせず対象だけ表示")
    parser.add_argument(
        "--delete-local",
        action="store_true",
        help="アップロード成功後に docs/episodes の実体を削除する",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help=(
            "一部の退避に失敗しても続行する。"
            "URL が確定したファイルだけ削除し、未退避の実体は Pages 配信を継続する"
        ),
    )
    args = parser.parse_args()

    repo = os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO)
    ia_prefix = os.environ.get("IA_ITEM_PREFIX", DEFAULT_IA_PREFIX)
    token = os.environ.get("GITHUB_TOKEN", "")
    ia_access = os.environ.get("IA_ACCESS_KEY", "")
    ia_secret = os.environ.get("IA_SECRET_KEY", "")

    cfg = load_archive_config()

    # GitHub Releases は無料・容量無制限なので既定で有効
    skip_github = os.environ.get("ARCHIVE_SKIP_GITHUB") == "1" or not cfg.get(
        "github_releases", True
    )

    # archive.org はサービス依存のため既定で無効。meta で有効化した場合のみ動く
    ia_enabled = bool(cfg.get("internet_archive", False))
    ia_env = os.environ.get("ARCHIVE_SKIP_IA")
    if ia_env == "1":
        ia_enabled = False
    elif ia_env == "0":
        # 明示的に 0 を渡されたら meta の設定より優先して有効化する
        ia_enabled = True
    if ia_enabled and not (ia_access and ia_secret):
        log(
            "[archive] WARNING: archive.org is enabled but "
            "IA_ACCESS_KEY / IA_SECRET_KEY are not set - skipping archive.org"
        )
        ia_enabled = False
    skip_ia = not ia_enabled

    if not args.dry_run:
        if skip_github and skip_ia:
            raise SystemExit(
                "nothing to do: both GitHub Releases and archive.org are disabled"
            )
        if not skip_github and not token:
            raise SystemExit("GITHUB_TOKEN is required (or set ARCHIVE_SKIP_GITHUB=1)")

    targets = collect_targets(args.all)
    log(f"[archive] target episodes: {len(targets)}")
    log(
        f"[archive] destinations: github_releases={'off' if skip_github else 'on'}, "
        f"internet_archive={'off' if skip_ia else 'on'}"
    )

    if args.dry_run:
        for mp3 in targets:
            dest = f"tag={_month_tag(mp3)}"
            if not skip_ia:
                dest += f"  item={ia_prefix}-{os.path.basename(mp3)[:7]}"
            log(f"  {mp3}  -> {dest}")
        return 0

    # 月ごとにまとめてアップロードする
    by_month: dict[str, list[str]] = {}
    for mp3 in targets:
        by_month.setdefault(_month_tag(mp3), []).append(mp3)

    url_map: dict[str, str] = {}
    failures: list[str] = []

    total_months = len(by_month)
    for month_idx, (tag, mp3s) in enumerate(sorted(by_month.items()), start=1):
        month = tag.removeprefix(RELEASE_TAG_PREFIX)
        identifier = f"{ia_prefix}-{month}"
        files: list[str] = []
        for mp3 in mp3s:
            files.extend(_episode_files(mp3))

        log(
            f"[archive] === [{month_idx}/{total_months}] {month}: "
            f"{len(mp3s)} episode(s), {len(files)} file(s) ==="
        )
        started = time.monotonic()

        gh_urls: dict[str, str] = {}
        if not skip_github:
            try:
                release = ensure_release(tag, token, repo)
                for i, path in enumerate(files, start=1):
                    log(f"[archive]   github {i}/{len(files)}: {os.path.basename(path)}")
                    gh_urls[os.path.basename(path)] = upload_release_asset(release, path, token)
            except Exception as exc:  # noqa: BLE001
                log(f"[archive] ERROR github release {tag}: {exc}")
                failures.append(f"github:{tag}")

        if not skip_ia:
            try:
                log(f"[archive]   archive.org: uploading {len(files)} file(s) -> {identifier}")
                upload_to_archive(files, identifier, ia_access, ia_secret)
            except Exception as exc:  # noqa: BLE001
                log(f"[archive] ERROR archive.org {identifier}: {exc}")
                failures.append(f"archive.org:{identifier}")

        for path in files:
            name = os.path.basename(path)
            # 配信元は常に GitHub Releases を優先する。
            # archive.org は SLA・帯域の保証がないため enclosure には使わない。
            if name in gh_urls:
                url_map[name] = gh_urls[name]
            elif not skip_ia:
                url_map[name] = archive_url(identifier, name)

        log(
            f"[archive] --- [{month_idx}/{total_months}] {month} done "
            f"in {time.monotonic() - started:.1f}s ---"
        )

    rewrite_feed(FEED_PATH, url_map)

    if failures:
        log(f"[archive] completed with failures: {', '.join(failures)}")
        if not args.allow_partial:
            # 退避に失敗したファイルは消さない（Pages から配信を継続する）
            log("[archive] local files kept to avoid broken enclosures")
            return 1
        log("[archive] --allow-partial: deleting only files with a resolved URL")

    if args.delete_local:
        removed = 0
        kept = 0
        for mp3 in targets:
            for path in _episode_files(mp3):
                if not os.path.exists(path):
                    continue
                # URL が確定したファイルだけ削除する（未退避の実体は Pages 配信を継続）
                if os.path.basename(path) not in url_map:
                    kept += 1
                    continue
                os.remove(path)
                removed += 1
        log(f"[archive] removed {removed} local file(s) from {EPISODES_DIR}")
        if kept:
            log(f"[archive] kept {kept} local file(s) without a resolved URL")

    log("[archive] done")
    return 1 if failures and not args.allow_partial else 0


if __name__ == "__main__":
    raise SystemExit(main())
