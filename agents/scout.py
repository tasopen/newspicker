"""@scout: AIニュース収集エージェント

NewsAPI と RSS フィードから過去24時間のAI記事を収集し、
重要度スコアで上位N件を返す。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser
import requests
import yaml
from dateutil import parser as dtparser


@dataclass
class Article:
    title: str
    url: str
    summary: str
    published_at: datetime
    source: str
    score: float = 0.0


def _load_config(config_path: str = "config/sources.yml") -> dict[str, Any]:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _score(article: Article, config: dict[str, Any]) -> float:
    keywords = [kw.lower() for kw in config["newsapi"]["keywords"]]
    text = (article.title + " " + article.summary).lower()
    return sum(1.0 for kw in keywords if kw in text)


def fetch_newsapi(config: dict[str, Any], api_key: str) -> list[Article]:
    """NewsAPI から記事を取得する。"""
    since = (datetime.now(timezone.utc) - timedelta(hours=config["selection"]["hours_lookback"])).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    params = {
        "q": " OR ".join(config["newsapi"]["keywords"]),
        "language": config["newsapi"]["language"],
        "from": since,
        "pageSize": config["newsapi"]["page_size"],
        "sortBy": "publishedAt",
        "apiKey": api_key,
    }
    resp = requests.get("https://newsapi.org/v2/everything", params=params, timeout=15)
    resp.raise_for_status()
    articles = []
    for item in resp.json().get("articles", []):
        if not item.get("url") or "[Removed]" in (item.get("title") or ""):
            continue
        try:
            pub = dtparser.parse(item["publishedAt"]).replace(tzinfo=timezone.utc)
        except Exception:
            continue
        articles.append(
            Article(
                title=item.get("title") or "",
                url=item["url"],
                summary=item.get("description") or item.get("content") or "",
                published_at=pub,
                source=item.get("source", {}).get("name", "NewsAPI"),
            )
        )
    return articles


def fetch_rss(feed_cfg: dict[str, Any], hours: int) -> list[Article]:
    """RSS フィードから記事を取得する。"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    parsed = feedparser.parse(feed_cfg["url"])
    articles = []
    for entry in parsed.entries:
        pub_struct = entry.get("published_parsed") or entry.get("updated_parsed")
        if not pub_struct:
            continue
        pub = datetime(*pub_struct[:6], tzinfo=timezone.utc)
        if pub < cutoff:
            continue
        articles.append(
            Article(
                title=entry.get("title") or "",
                url=entry.get("link") or "",
                summary=entry.get("summary") or "",
                published_at=pub,
                source=feed_cfg["name"],
                score=feed_cfg.get("weight", 1.0),
            )
        )
    return articles


def collect(config_path: str = "config/sources.yml") -> list[Article]:
    """全ソースから記事を収集し、スコア順上位N件を返す。"""
    config = _load_config(config_path)
    api_key = os.environ.get("NEWS_API_KEY", "")
    hours = config["selection"]["hours_lookback"]
    max_n = config["selection"]["max_articles"]

    all_articles: list[Article] = []

    # NewsAPI
    if api_key:
        try:
            all_articles.extend(fetch_newsapi(config, api_key))
        except Exception as e:
            print(f"[scout] NewsAPI error: {e}")

    # RSS フィード
    for feed_cfg in config.get("rss_feeds", []):
        try:
            all_articles.extend(fetch_rss(feed_cfg, hours))
            time.sleep(0.3)
        except Exception as e:
            print(f"[scout] RSS error ({feed_cfg['name']}): {e}")

    # 重複排除（URL ベース）
    seen: set[str] = set()
    unique: list[Article] = []
    for a in all_articles:
        if a.url not in seen and a.url:
            seen.add(a.url)
            # スコアにキーワードマッチを加算
            a.score += _score(a, config)
            unique.append(a)

    # スコア降順でソートして上位N件
    unique.sort(key=lambda a: (a.score, a.published_at), reverse=True)
    selected = unique[:max_n]
    print(f"[scout] {len(all_articles)} articles fetched → {len(selected)} selected")
    return selected


if __name__ == "__main__":
    articles = collect()
    for a in articles:
        print(f"  [{a.source}] {a.title} ({a.published_at.date()})")
