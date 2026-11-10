#!/usr/bin/env python3
"""GitHub Releases の音声を archive.org へ複製する（ローカル実行用）。

`archive_episode.py` は docs/episodes に実体がある前提だが、移行後は
実体が GitHub Releases にしかない。このスクリプトは Release から
ダウンロードして archive.org へアップロードする。

使い方:
  # 何が足りないか確認するだけ
  python scripts/mirror_to_archive_org.py --dry-run

  # 不足分をすべて複製
  python scripts/mirror_to_archive_org.py

  # 特定の月だけ
  python scripts/mirror_to_archive_org.py --month 2026-03

必要な環境変数:
  IA_ACCESS_KEY    archive.org の S3 アクセスキー
  IA_SECRET_KEY    archive.org の S3 シークレットキー

任意の環境変数:
  GITHUB_TOKEN     Release 取得用（公開リポジトリなら不要）
  GITHUB_REPOSITORY  既定: tasopen/newspicker
  IA_ITEM_PREFIX     既定: newspicker-tasopen
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time

import requests

DEFAULT_REPO = "tasopen/newspicker"
DEFAULT_IA_PREFIX = "newspicker-tasopen"
RELEASE_TAG_PREFIX = "episodes-"
GH_API = "https://api.github.com"
IA_METADATA = "https://archive.org/metadata"


def log(msg: str) -> None:
    print(msg, flush=True)


def load_dotenv(path: str = ".env") -> None:
    """python-dotenv が無くても .env を読めるようにする簡易ローダー。"""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _fmt_dur(sec: float) -> str:
    sec = int(sec)
    if sec < 60:
        return f"{sec}s"
    m, s = divmod(sec, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def _gh_headers(token: str) -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def release_assets(tag: str, token: str, repo: str) -> dict[str, str]:
    """Release のアセット名 -> ダウンロード URL を返す。"""
    r = requests.get(
        f"{GH_API}/repos/{repo}/releases/tags/{tag}",
        headers=_gh_headers(token),
        timeout=30,
    )
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    return {a["name"]: a["browser_download_url"] for a in r.json().get("assets", [])}


def archive_files(identifier: str) -> set[str]:
    """archive.org アイテムに既にあるファイル名を返す。"""
    try:
        r = requests.get(f"{IA_METADATA}/{identifier}", timeout=30)
        if r.status_code == 404:
            return set()
        r.raise_for_status()
        return {f["name"] for f in r.json().get("files", [])}
    except Exception as exc:  # noqa: BLE001
        log(f"[mirror] WARN metadata fetch failed for {identifier}: {exc}")
        return set()


def download(url: str, dest: str, token: str) -> int:
    """ダウンロードしてバイト数を返す。"""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    total = 0
    with requests.get(url, headers=headers, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                total += len(chunk)
    return total


def upload(paths: list[str], identifier: str, access: str, secret: str) -> None:
    from internetarchive import upload as ia_upload

    metadata = {
        "title": f"朝刊ワールドAIニュース {identifier.rsplit('-', 1)[-1]}",
        "mediatype": "audio",
        "collection": "opensource_audio",
        "creator": "TasogarePenguin",
        "language": "jpn",
        "subject": "podcast; AI news; ポッドキャスト",
        "description": "AI ニュースのポッドキャスト音声アーカイブ。",
    }
    responses = ia_upload(
        identifier,
        files=paths,
        metadata=metadata,
        access_key=access,
        secret_key=secret,
        queue_derive=False,
        retries=5,
        verbose=True,
    )
    for resp in responses:
        status = getattr(resp, "status_code", None)
        if status is not None and status >= 400:
            raise RuntimeError(f"archive.org upload failed ({status}): {resp.text[:300]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="不足分の表示のみ")
    parser.add_argument("--month", help="対象月を限定（例: 2026-03）")
    parser.add_argument(
        "--months",
        default="2026-02,2026-03,2026-04,2026-05,2026-06,2026-07,2026-08,2026-09,2026-10,2026-11",
        help="対象月のカンマ区切り",
    )
    args = parser.parse_args()

    load_dotenv()

    repo = os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO)
    prefix = os.environ.get("IA_ITEM_PREFIX", DEFAULT_IA_PREFIX)
    token = os.environ.get("GITHUB_TOKEN", "")
    access = os.environ.get("IA_ACCESS_KEY", "")
    secret = os.environ.get("IA_SECRET_KEY", "")

    if not args.dry_run and not (access and secret):
        raise SystemExit("IA_ACCESS_KEY / IA_SECRET_KEY are required")

    months = [args.month] if args.month else [m.strip() for m in args.months.split(",") if m.strip()]

    total_missing = 0
    plan: list[tuple[str, str, list[str]]] = []

    for month in months:
        tag = RELEASE_TAG_PREFIX + month
        identifier = f"{prefix}-{month}"
        assets = release_assets(tag, token, repo)
        if not assets:
            log(f"[mirror] {month}: no release assets, skipped")
            continue
        have = archive_files(identifier)
        missing = sorted(n for n in assets if n not in have)
        total_missing += len(missing)
        log(f"[mirror] {month}: release={len(assets)} archive.org={len(have)} missing={len(missing)}")
        if missing:
            plan.append((identifier, tag, missing))

    log(f"[mirror] total missing files: {total_missing}")
    if args.dry_run or not plan:
        return 0

    failures: list[str] = []
    grand_started = time.monotonic()
    done_files = 0
    done_bytes = 0
    total_files = sum(len(m) for _, _, m in plan)

    for month_idx, (identifier, tag, missing) in enumerate(plan, start=1):
        log("")
        log(f"[mirror] ===== [{month_idx}/{len(plan)}] {identifier}: {len(missing)} file(s) =====")
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as tmp:
            paths: list[str] = []
            for i, name in enumerate(missing, start=1):
                dest = os.path.join(tmp, name)
                t0 = time.monotonic()
                try:
                    size = download(
                        f"https://github.com/{repo}/releases/download/{tag}/{name}",
                        dest,
                        token,
                    )
                    paths.append(dest)
                    done_bytes += size
                    log(
                        f"[mirror]   dl {i}/{len(missing)} {name} "
                        f"({_fmt_size(size)}, {time.monotonic() - t0:.1f}s)"
                    )
                except Exception as exc:  # noqa: BLE001
                    log(f"[mirror]   ERROR download {name}: {exc}")
                    failures.append(f"{identifier}/{name}")

            if not paths:
                continue

            # 1ファイルずつアップロードして進捗を可視化する
            for i, path in enumerate(paths, start=1):
                name = os.path.basename(path)
                t0 = time.monotonic()
                try:
                    upload([path], identifier, access, secret)
                    done_files += 1
                    elapsed = time.monotonic() - grand_started
                    rate = done_files / elapsed if elapsed > 0 else 0
                    remain = (total_files - done_files) / rate if rate > 0 else 0
                    pct = done_files / total_files * 100 if total_files else 100
                    log(
                        f"[mirror]   up {i}/{len(paths)} {name} "
                        f"({time.monotonic() - t0:.1f}s) | "
                        f"total {done_files}/{total_files} ({pct:.0f}%) "
                        f"elapsed {_fmt_dur(elapsed)} ETA {_fmt_dur(remain)}"
                    )
                except Exception as exc:  # noqa: BLE001
                    log(f"[mirror]   ERROR upload {name}: {exc}")
                    failures.append(f"{identifier}/{name} (upload)")

        log(
            f"[mirror] --- {identifier} done in {_fmt_dur(time.monotonic() - started)} "
            f"({len(paths)} file(s)) ---"
        )

    log("")
    log(
        f"[mirror] finished: {done_files}/{total_files} uploaded, "
        f"{_fmt_size(done_bytes)} downloaded, "
        f"total {_fmt_dur(time.monotonic() - grand_started)}"
    )
    if failures:
        log(f"[mirror] completed with {len(failures)} failure(s):")
        for f in failures:
            log(f"  - {f}")
        return 1

    log("[mirror] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
