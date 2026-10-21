"""Extract only quest prerequisite cells from a user-supplied wikiwiki HAR.

Offline maintenance tool: pip install beautifulsoup4, then pass the HAR path.
The HAR itself is not committed; request headers and unrelated responses are
never copied into the extracted data.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
CODE = re.compile(r"\(([0-9]*[A-Za-z]+\s*[0-9]+)\)")


def extract(path):
    har = json.loads(path.read_text(encoding="utf-8-sig"))
    entry = next(e for e in har["log"]["entries"]
                 if unquote(e["request"]["url"]).split("?")[0]
                 == "https://wikiwiki.jp/kancolle/任務/出撃任務")
    content = entry["response"]["content"]
    html = content["text"]
    if content.get("encoding") == "base64":
        html = base64.b64decode(html).decode("utf-8")
    soup = BeautifulSoup(html, "html.parser")
    rows = {}
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 9:
            continue
        code = cells[0].get_text(strip=True)
        if not re.fullmatch(r"B[0-9]+", code):
            continue
        cell = cells[8]
        text = cell.get_text(" ", strip=True)
        refs = list(dict.fromkeys(re.sub(r"\s", "", c) for c in CODE.findall(text)))
        # Confirmed title match: this wiki snapshot uses a provisional code
        # for the same title stored as EO By17 / TsunKit 2609By1.
        aliases = {"2609B1": "By17"}
        refs = [aliases.get(c, c) for c in refs]
        row = {"prerequisites": refs, "text_jp": text,
               "wiki_unverified": bool(re.search("検証中|要検証|要確認", text))}
        if "または" in text:
            if code != "B48":
                raise ValueError(f"Review alternative prerequisite grouping: {code}")
            row["any_of"] = [["Bd1", "Bd2"]]
        if "からCy11に変更" in text:
            row["replaces"] = ["2307B1"]
        rows[code] = row
    assert len(rows) == 217, f"Unexpected table size: {len(rows)}"
    assert rows["B208"]["prerequisites"] == ["B35"]
    result = {"source": {"url": entry["request"]["url"],
                         "captured_at": entry.get("startedDateTime"),
                         "html_sha256": hashlib.sha256(html.encode()).hexdigest(),
                         "code_aliases": {"2609B1": "By17"}},
              "quests": rows}
    output = ROOT / "data/quest_wiki_prereqs.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Extracted {len(rows)} prerequisite cells into {output.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("har", type=Path)
    extract(parser.parse_args().har)
