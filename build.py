#!/usr/bin/env python3
"""pdfs/ 폴더를 훑어서 manifest.json(목록)을 만든다.

사용법:  python3 build.py

- pdfs/ 안의 PDF를 모두 찾는다. 폴더 이름이 '분류'가 되고, 그 안의 폴더는 '소분류'가 된다.
    pdfs/전기이론/01_옴의법칙.pdf          ->  분류 "전기이론", 제목 "옴의법칙"
    pdfs/전기이론/직류회로/01_키르히호프.pdf ->  분류 "전기이론", 소분류 "직류회로"
    pdfs/계산공식집.pdf                    ->  분류 "기타",     제목 "계산공식집"
- 파일 이름 앞의 "01_", "02-" 같은 번호는 정렬에만 쓰고 제목에서는 뺀다.
- 쪽수는 pypdf가 설치되어 있으면 함께 기록한다 (pip install pypdf). 없어도 동작한다.
- 표지 이미지(첫 쪽 그림)는 PyMuPDF가 설치되어 있으면 thumbs/ 폴더에 미리 만든다 (pip install pymupdf).
  없으면 사이트가 접속한 사람의 휴대폰에서 직접 만들어 쓴다. 자동 배포(GitHub Actions)에서는 항상 만든다.
"""
import hashlib
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
THUMB_DIR = ROOT / "thumbs"
DEFAULT_CATEGORY = "기타"
THUMB_SIZES = (("m", 520), ("s", 220))   # 큰 표지(카드·최근 추가) / 작은 표지(분류 카드·목록)

try:
    from pypdf import PdfReader
except ImportError:  # 쪽수 표시는 선택 사항
    PdfReader = None

try:
    import pymupdf as fitz  # PyMuPDF (새 이름)
except ImportError:
    try:
        import fitz  # PyMuPDF (옛 이름)
    except ImportError:  # 표지 이미지는 선택 사항
        fitz = None


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


def make_thumbs(path: Path, rel_key: str, size: int):
    """PDF 첫 쪽을 그림 두 장(큰 것/작은 것)으로 만든다. 반환: {"m": 경로, "s": 경로} (못 만들면 {})."""
    if fitz is None:
        return {}
    base = hashlib.sha1(rel_key.encode("utf-8")).hexdigest()[:10] + f"-{size}"
    out = {k: THUMB_DIR / f"{base}-{k}.jpg" for k, _ in THUMB_SIZES}
    try:
        if not all(p.exists() for p in out.values()):
            THUMB_DIR.mkdir(exist_ok=True)
            doc = fitz.open(str(path))
            page = doc[0]
            for k, width in THUMB_SIZES:
                zoom = width / page.rect.width
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                try:
                    data = pix.tobytes("jpeg", jpg_quality=76)
                except TypeError:
                    data = pix.tobytes("jpeg")
                out[k].write_bytes(data)
            doc.close()
        return {k: "thumbs/" + p.name for k, p in out.items()}
    except Exception as e:  # 표지를 못 만들어도 목록은 정상 동작
        print(f"  표지 생성 실패: {path.name} ({e})")
        return {}


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
        thumbs = make_thumbs(path, "/".join(rel.parts), stat.st_size)
        items.append(
            {
                "title": clean_title(Path(parts[-1]).stem),
                "category": category,
                "sub": sub,
                "path": web_path,
                "size": stat.st_size,
                "pages": page_count(path),
                "updated": updated,
                **({"thumb": thumbs["m"], "thumb_s": thumbs["s"]} if thumbs else {}),
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
    if fitz is None:
        note += "  (pymupdf가 없어 표지 이미지는 생략)"
    print(f"PDF {len(items)}개, 분류 {len(categories)}개 -> manifest.json{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
