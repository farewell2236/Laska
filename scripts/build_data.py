\
#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, Page, Response

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_JSON = ROOT / "data" / "songs.json"
OUTPUT_JS = ROOT / "data" / "songs.js"

SOURCES = {
    "normal": "https://iidx-difficulty-table-checker.nomadblacky.dev/table/12_normal",
    "hard": "https://iidx-difficulty-table-checker.nomadblacky.dev/table/12_hard",
}
RANKS = [
    "未定", "地力S+", "個人差S+", "地力S", "個人差S", "地力A+", "個人差A+",
    "地力A", "個人差A", "地力B+", "個人差B+", "地力B", "個人差B",
    "地力C", "個人差C", "地力D", "個人差D", "地力E", "個人差E",
    "地力F", "個人差F", "未分類",
]


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_rank(value: Any) -> str:
    text = clean(value)
    text = re.sub(r"[（(]\s*\d+\s*曲?\s*[)）]", "", text)
    for rank in RANKS:
        if text == rank or text.startswith(rank):
            return rank
    match = re.search(r"(個人差|地力)?\s*([S-F])\s*(\+)?", text, re.I)
    if match:
        return f"{match.group(1) or '地力'}{match.group(2).upper()}{match.group(3) or ''}"
    return "未分類"


def looks_like_song_title(value: Any) -> bool:
    text = clean(value)
    if not text or len(text) > 180:
        return False
    rejected = {
        "曲名", "title", "music", "難易度", "地力", "ランク", "version", "ver",
        "ノマゲ", "ハード", "未分類",
    }
    return text.lower() not in rejected and not re.fullmatch(r"[-–—:|\s]+", text)


def dedupe(items: list[dict[str, str]]) -> list[dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for item in items:
        title = clean(item.get("title"))
        if not looks_like_song_title(title):
            continue
        chart = clean(item.get("chart"))
        ver = clean(item.get("ver")) or "-"
        rank = normalize_rank(item.get("rank"))
        key = f"{title}::{chart}"
        result.setdefault(key, {"title": title, "chart": chart, "ver": ver, "rank": rank})
    return sorted(result.values(), key=lambda x: (RANKS.index(x["rank"]) if x["rank"] in RANKS else 999, x["title"]))


def walk_json(node: Any, inherited_rank: str = "未分類") -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    if isinstance(node, list):
        for value in node:
            found.extend(walk_json(value, inherited_rank))
        return found
    if not isinstance(node, dict):
        return found

    rank = inherited_rank
    for key in ("rank", "difficulty", "tier", "category", "label", "group"):
        if key in node:
            candidate = normalize_rank(node[key])
            if candidate != "未分類" or clean(node[key]).startswith("未分類"):
                rank = candidate
                break

    title = None
    for key in ("title", "musicTitle", "music_title", "songName", "song_name", "name"):
        if key in node and looks_like_song_title(node[key]):
            title = clean(node[key])
            break

    if title:
        chart = clean(next((node[k] for k in ("chart", "difficultyName", "difficulty_name", "style") if k in node), ""))
        ver = clean(next((node[k] for k in ("version", "ver", "series") if k in node), "-"))
        found.append({"title": title, "chart": chart, "ver": ver, "rank": rank})

    for value in node.values():
        if isinstance(value, (dict, list)):
            found.extend(walk_json(value, rank))
    return found


async def extract_from_dom(page: Page) -> list[dict[str, str]]:
    return await page.evaluate(
        """(ranks) => {
          const clean = v => String(v ?? '').replace(/\\s+/g, ' ').trim();
          const normRank = value => {
            const text = clean(value).replace(/[（(]\\s*\\d+\\s*曲?\\s*[)）]/g, '');
            const direct = ranks.find(r => text === r || text.startsWith(r));
            if (direct) return direct;
            const m = text.match(/(個人差|地力)?\\s*([S-F])\\s*(\\+)?/i);
            return m ? `${m[1] || '地力'}${m[2].toUpperCase()}${m[3] || ''}` : '未分類';
          };
          const result = [];

          // 1. Semantic HTML tables
          document.querySelectorAll('table').forEach(table => {
            const rows = [...table.querySelectorAll('tr')];
            if (!rows.length) return;
            let titleIndex = -1, verIndex = -1, rankIndex = -1, chartIndex = -1, start = 0;
            for (let i = 0; i < Math.min(4, rows.length); i++) {
              const cells = [...rows[i].querySelectorAll('th,td')].map(c => clean(c.innerText));
              const ti = cells.findIndex(c => /曲名|title|music/i.test(c));
              if (ti >= 0) {
                titleIndex = ti;
                verIndex = cells.findIndex(c => /^ver|version|バージョン/i.test(c));
                rankIndex = cells.findIndex(c => /地力|難易度|rank|tier/i.test(c));
                chartIndex = cells.findIndex(c => /譜面|chart|difficulty name/i.test(c));
                start = i + 1;
                break;
              }
            }
            if (titleIndex < 0) return;
            rows.slice(start).forEach(row => {
              const cells = [...row.querySelectorAll('th,td')].map(c => clean(c.innerText));
              if (cells.length <= titleIndex) return;
              result.push({
                title: cells[titleIndex],
                ver: verIndex >= 0 ? cells[verIndex] : '-',
                chart: chartIndex >= 0 ? cells[chartIndex] : '',
                rank: rankIndex >= 0 ? normRank(cells[rankIndex]) : '未分類'
              });
            });
          });

          // 2. ARIA/data-grid based tables
          document.querySelectorAll('[role="row"]').forEach(row => {
            const cells = [...row.querySelectorAll('[role="cell"],[role="gridcell"],[role="columnheader"]')]
              .map(c => clean(c.innerText));
            if (cells.length < 2 || cells.some(c => /曲名|title/i.test(c))) return;
            const rankCell = cells.find(c => normRank(c) !== '未分類' || c.startsWith('未分類'));
            const title = cells.find(c => c !== rankCell && c.length > 1 && !/^\\d+$/.test(c));
            if (title) result.push({title, ver:'-', chart:'', rank:normRank(rankCell || '')});
          });

          // 3. Cards grouped below headings
          const headings = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role="heading"]')];
          headings.forEach(heading => {
            const rank = normRank(heading.innerText);
            if (rank === '未分類' && !clean(heading.innerText).startsWith('未分類')) return;
            let node = heading.nextElementSibling;
            let guard = 0;
            while (node && guard++ < 12 && !/^H[1-6]$/.test(node.tagName)) {
              node.querySelectorAll('a,li,[data-title]').forEach(el => {
                const title = clean(el.getAttribute('data-title') || el.innerText);
                if (title && title.length < 180 && !/^(詳細|戻る|次へ|前へ)$/.test(title)) {
                  result.push({title, ver:'-', chart:'', rank});
                }
              });
              node = node.nextElementSibling;
            }
          });
          return result;
        }""",
        RANKS,
    )


async def scrape(mode: str, url: str) -> list[dict[str, str]]:
    captured_json: list[Any] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 2000})

        async def capture(response: Response) -> None:
            content_type = (response.headers.get("content-type") or "").lower()
            if "json" not in content_type:
                return
            try:
                captured_json.append(await response.json())
            except Exception:
                pass

        page.on("response", capture)
        await page.goto(url, wait_until="networkidle", timeout=90_000)
        await page.wait_for_timeout(3000)

        # Scroll to trigger lazy rendering.
        await page.evaluate(
            """async () => {
              for (let y = 0; y < document.body.scrollHeight; y += 700) {
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, 80));
              }
              window.scrollTo(0, 0);
            }"""
        )

        dom_items = await extract_from_dom(page)

        # Next.js and other frameworks often embed state in script tags.
        embedded = await page.locator("script").all_text_contents()
        embedded_json: list[Any] = []
        for text in embedded:
            text = text.strip()
            if not text or len(text) < 2:
                continue
            try:
                embedded_json.append(json.loads(text))
            except Exception:
                # Search for JSON objects assigned in script text.
                if "__NEXT_DATA__" in text:
                    match = re.search(r"\{.*\}", text, re.S)
                    if match:
                        try:
                            embedded_json.append(json.loads(match.group(0)))
                        except Exception:
                            pass

        await browser.close()

    candidates = dom_items[:]
    for payload in captured_json + embedded_json:
        candidates.extend(walk_json(payload))

    result = dedupe(candidates)
    print(f"{mode}: DOM={len(dom_items)} JSON responses={len(captured_json)} result={len(result)}")
    if len(result) < 100:
        raise RuntimeError(
            f"{mode} の解析件数が不足しています ({len(result)}件)。"
            "サイト構造が変わった可能性があります。"
        )
    return result


async def main() -> None:
    normal, hard = await asyncio.gather(
        scrape("normal", SOURCES["normal"]),
        scrape("hard", SOURCES["hard"]),
    )
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sources": SOURCES,
        "normal": normal,
        "hard": hard,
    }
    OUTPUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    OUTPUT_JS.write_text(
        "window.IIDX_SP12_DATA = " +
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) +
        ";\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT_JSON} and {OUTPUT_JS}")


if __name__ == "__main__":
    asyncio.run(main())
