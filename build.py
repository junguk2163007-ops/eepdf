#!/usr/bin/env python3
"""pdfs/ 폴더를 훑어서 manifest.json(목록)을 만든다.

사용법:  python3 build.py

- pdfs/ 안의 PDF를 모두 찾는다. 폴더 이름이 '분류'가 되고, 그 안의 폴더는 '소분류'가 된다.
    pdfs/전기이론/01_옴의법칙.pdf          ->  분류 "전기이론", 제목 "옴의법칙"
    pdfs/전기이론/직류회로/01_키르히호프.pdf ->  분류 "전기이론", 소분류 "직류회로"
    pdfs/계산공식집.pdf                    ->  분류 "기타",     제목 "계산공식집"
- 파일 이름 앞의 "01_", "02-" 같은 번호는 정렬에만 쓰고 제목에서는 뺀다.
- 쪽수는 pypdf가 설치되어 있으면 함께 기록한다 (pip install pypdf). 없어도 동작한다.
"""
import json
import re
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
PDF_DIR = ROOT / "pdfs"
OUT = ROOT / "manifest.json"
DEFAULT_CATEGORY = "기타"

try:
    from pypdf import PdfReader
except ImportError:  # 쪽수 표시는 선택 사항
    PdfReader = None


def nfc(text: str) -> str:
    # macOS는 한글 파일명을 자모 분리(NFD)로 저장하므로 합쳐 준다.
    return unicodedata.normalize("NFC", text)


def natural_key(text: str):
    # (0, 숫자) / (1, 문자) 쌍으로 만들어 숫자와 문자가 섞여도 비교되게 한다
    return [(0, int(t), "") if t.isdigit() else (1, 0, t.lower()) for t in re.findall(r"\d+|\D+", text)]


def clean_title(stem: str) -> str:
    title = re.sub(r"^\s*\d+\s*[_\-.)]\s*", "", stem)  # 앞 번호 제거
    title = re.sub(r"[_]+", " ", title).strip()
    return title or stem


def page_count(path: Path):
    if PdfReader is None:
        return None
    try:
        return len(PdfReader(str(path)).pages)
    except Exception:
        return None


def previous_dates():
    """이전 manifest.json에 기록된 날짜(경로 -> (날짜, 크기)). 내려받기 등으로 수정일이 바뀌어도 NEW 표시가 흔들리지 않게 한다."""
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
        return {i["path"]: (i.get("updated"), i.get("size")) for i in old.get("items", [])}
    except Exception:
        return {}


def git_date(path: Path):
    """git에 올라간 파일이면 마지막으로 바뀐 날짜(커밋 날짜). 아니면 None."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "--", str(path)],
            cwd=ROOT, capture_output=True, text=True, timeout=20,
        ).stdout.strip()
        return out or None
    except Exception:
        return None


def main() -> int:
    PDF_DIR.mkdir(exist_ok=True)
    prev = previous_dates()
    items = []
    for path in sorted(PDF_DIR.rglob("*"), key=lambda p: natural_key(nfc(str(p)))):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue
        rel = path.relative_to(PDF_DIR)
        parts = [nfc(p) for p in rel.parts]
        category = clean_title(parts[0]) if len(parts) > 1 else DEFAULT_CATEGORY
        sub = " / ".join(clean_title(x) for x in parts[1:-1])  # 소분류(폴더가 2단계 이상일 때)
        stat = path.stat()
        web_path = "pdfs/" + "/".join(quote(p) for p in rel.parts)
        old_date, old_size = prev.get(web_path, (None, None))
        if old_date and old_size == stat.st_size:
            updated = old_date                      # 그대로면 예전 날짜 유지
        else:
            updated = git_date(path) or datetime.fromtimestamp(stat.st_mtime, timezone.utc).strftime("%Y-%m-%d")
        items.append(
            {
                "title": clean_title(Path(parts[-1]).stem),
                "category": category,
                "sub": sub,
                "path": web_path,
                "size": stat.st_size,
                "pages": page_count(path),
                "updated": updated,
                "_sort": [natural_key(parts[0]) if len(parts) > 1 else [(2, 0, "")], [natural_key(x) for x in parts[1:-1]], natural_key(parts[-1])],
            }
        )

    items.sort(key=lambda i: i["_sort"])
    categories = []
    for i in items:
        i.pop("_sort")
        if i["category"] not in categories:
            categories.append(i["category"])

    OUT.write_text(
        json.dumps(
            {
                "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "categories": categories,
                "items": items,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    note = "" if PdfReader else "  (pypdf가 없어 쪽수는 생략)"
    print(f"PDF {len(items)}개, 분류 {len(categories)}개 -> manifest.json{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
