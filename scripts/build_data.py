\
#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, Page

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
    match = re.search(r"(個人差|地力)?\s*([A-FS])\s*(\+)?", text, re.I)
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
    """Extract only rows currently rendered on the requested table page.

    The site preloads data for other difficulty tables, including ☆11.
    Reading every JSON response or every script tag therefore mixes levels.
    This function intentionally reads only visible DOM rows on the current page.
    """
    return await page.evaluate(
        """(ranks) => {
          const clean = v => String(v ?? '').replace(/\\s+/g, ' ').trim();
          const visible = el => {
            if (!el) return false;
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' &&
                   style.visibility !== 'hidden' &&
                   rect.width > 0 &&
                   rect.height > 0;
          };
          const normRank = value => {
            const text = clean(value).replace(/[（(]\\s*\\d+\\s*曲?\\s*[)）]/g, '');
            const direct = ranks.find(r => text === r || text.startsWith(r));
            if (direct) return direct;
            const m = text.match(/(個人差|地力)?\\s*([A-FS])\\s*(\\+)?/i);
            return m ? `${m[1] || '地力'}${m[2].toUpperCase()}${m[3] || ''}` : '未分類';
          };
          const result = [];

          document.querySelectorAll('table').forEach(table => {
            if (!visible(table)) return;

            const rows = [...table.querySelectorAll('tr')].filter(visible);
            if (!rows.length) return;

            let titleIndex = -1;
            let verIndex = -1;
            let rankIndex = -1;
            let chartIndex = -1;
            let levelIndex = -1;
            let start = 0;

            for (let i = 0; i < Math.min(5, rows.length); i++) {
              const cells = [...rows[i].querySelectorAll('th,td')].map(c => clean(c.innerText));
              const ti = cells.findIndex(c => /曲名|title|music/i.test(c));
              if (ti < 0) continue;

              titleIndex = ti;
              verIndex = cells.findIndex(c => /^ver|version|バージョン/i.test(c));
              rankIndex = cells.findIndex(c => /地力|難易度|rank|tier/i.test(c));
              chartIndex = cells.findIndex(c => /譜面|chart|difficulty name/i.test(c));
              levelIndex = cells.findIndex(c => /レベル|level|☆/i.test(c));
              start = i + 1;
              break;
            }

            if (titleIndex < 0) return;

            rows.slice(start).forEach(row => {
              const cells = [...row.querySelectorAll('th,td')].map(c => clean(c.innerText));
              if (cells.length <= titleIndex) return;

              // If the page exposes a level column, accept ☆12 only.
              if (levelIndex >= 0) {
                const levelText = clean(cells[levelIndex]);
                const levelMatch = levelText.match(/(?:☆|LV\\.?|LEVEL\\s*)?(\\d{1,2})/i);
                if (levelMatch && Number(levelMatch[1]) !== 12) return;
              }

              const title = clean(cells[titleIndex]);
              if (!title || /(?:^|\\s)☆?11(?:\\s|$)/.test(title)) return;

              result.push({
                title,
                ver: verIndex >= 0 ? cells[verIndex] : '-',
                chart: chartIndex >= 0 ? cells[chartIndex] : '',
                rank: rankIndex >= 0 ? normRank(cells[rankIndex]) : '未分類'
              });
            });
          });

          // Some UI libraries render a grid rather than a semantic table.
          document.querySelectorAll('[role="table"],[role="grid"]').forEach(grid => {
            if (!visible(grid)) return;

            const rows = [...grid.querySelectorAll('[role="row"]')].filter(visible);
            if (rows.length < 2) return;

            const header = [...rows[0].querySelectorAll(
              '[role="columnheader"],[role="cell"],[role="gridcell"]'
            )].map(c => clean(c.innerText));

            const titleIndex = header.findIndex(c => /曲名|title|music/i.test(c));
            if (titleIndex < 0) return;

            const verIndex = header.findIndex(c => /^ver|version|バージョン/i.test(c));
            const rankIndex = header.findIndex(c => /地力|難易度|rank|tier/i.test(c));
            const chartIndex = header.findIndex(c => /譜面|chart|difficulty name/i.test(c));
            const levelIndex = header.findIndex(c => /レベル|level|☆/i.test(c));

            rows.slice(1).forEach(row => {
              const cells = [...row.querySelectorAll(
                '[role="cell"],[role="gridcell"]'
              )].map(c => clean(c.innerText));
              if (cells.length <= titleIndex) return;

              if (levelIndex >= 0) {
                const levelMatch = clean(cells[levelIndex]).match(
                  /(?:☆|LV\\.?|LEVEL\\s*)?(\\d{1,2})/i
                );
                if (levelMatch && Number(levelMatch[1]) !== 12) return;
              }

              result.push({
                title: cells[titleIndex],
                ver: verIndex >= 0 ? cells[verIndex] : '-',
                chart: chartIndex >= 0 ? cells[chartIndex] : '',
                rank: rankIndex >= 0 ? normRank(cells[rankIndex]) : '未分類'
              });
            });
          });

          return result;
        }""",
        RANKS,
    )


async def scrape(mode: str, url: str) -> list[dict[str, str]]:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 2000})

        print(f"{mode}: opening {url}", flush=True)
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(5000)
        print(f"{mode}: page opened", flush=True)
        current_path = await page.evaluate("location.pathname")
        expected_path = "/table/12_normal" if mode == "normal" else "/table/12_hard"
        if current_path.rstrip("/") != expected_path:
            raise RuntimeError(
                f"{mode}: 想定外のページへ移動しました: {current_path} "
                f"(expected {expected_path})"
            )

        # Scroll to trigger lazy rendering.
        # Bounded scrolling prevents infinite-scroll pages from running forever.
        print(f"{mode}: scrolling page", flush=True)
        await page.evaluate(
            """async () => {
              let previousHeight = 0;
              let stableRounds = 0;
              for (let round = 0; round < 40; round++) {
                const height = document.body.scrollHeight;
                window.scrollTo(0, height);
                await new Promise(r => setTimeout(r, 250));

                const nextHeight = document.body.scrollHeight;
                if (nextHeight === previousHeight) {
                  stableRounds += 1;
                } else {
                  stableRounds = 0;
                }
                previousHeight = nextHeight;

                if (stableRounds >= 3) break;
              }
              window.scrollTo(0, 0);
            }"""
        )
        print(f"{mode}: scrolling complete", flush=True)

        print(f"{mode}: extracting DOM data", flush=True)
        dom_items = await extract_from_dom(page)
        print(f"{mode}: DOM candidates={len(dom_items)}", flush=True)

        print(f"{mode}: closing browser", flush=True)
        await browser.close()

    result = dedupe(dom_items)
    print(f"{mode}: visible DOM={len(dom_items)} result={len(result)}", flush=True)

    # A valid ☆12 table should contain hundreds of charts, but never thousands.
    # The upper bound detects accidental inclusion of prefetched ☆11 data.
    if not 100 <= len(result) <= 900:
        raise RuntimeError(
            f"{mode} の☆12解析件数が想定外です ({len(result)}件)。"
            "他レベルが混ざったか、サイト構造が変わった可能性があります。"
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
    print(f"Wrote {OUTPUT_JSON} and {OUTPUT_JS}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
