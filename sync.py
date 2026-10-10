"""Refresh the Flower Inventory page data from its Google Sheet.

Usage: SHEET_ID=... python3 sync.py
Replaces the contents of <script type="application/json" id="flower-data"> in index.html,
rewrites images.json (small thumbnails) and writes a high-resolution copy of each photo to photos/. Exits non-zero without writing anything if the sheet is not readable.
The sheet ID comes from the environment so it never appears in this public repository.
"""
import base64, csv, datetime, hashlib, io, json, os, re, sys, urllib.request
import html as html_lib
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from PIL import Image, ImageOps

SHEET = "https://docs.google.com/spreadsheets/d/" + os.environ["SHEET_ID"]
IMG_WIDTH, WEBP_QUALITY = 360, 70          # thumbnails, inlined in images.json
PHOTO_MAX, PHOTO_QUALITY = 2400, 90        # detail photos: longest side in pixels, one file each in photos/
PHOTO_DIR = "photos"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(), r.headers.get("Content-Type", "")


class SheetImages(HTMLParser):
    """Collects {sheet row number: first image URL in that row} from the htmlview table."""
    def __init__(self):
        super().__init__()
        self.images, self.row, self.cell, self.rownum = {}, False, -1, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self.row, self.cell, self.rownum = True, -1, None
        elif tag in ("td", "th") and self.row:
            self.cell += 1
        elif tag == "img" and self.rownum and self.cell > 0 and "sheets-images-rt" in a.get("src", ""):
            self.images.setdefault(self.rownum, a["src"])

    def handle_data(self, data):
        if self.row and self.cell == 0 and data.strip().isdigit() and self.rownum is None:
            self.rownum = int(data.strip())


def webp_bytes(im, quality):
    out = io.BytesIO()
    im.save(out, "WEBP", quality=quality, method=6)
    return out.getvalue()


def photo(url, out_dir):
    """Downloads the original image once and returns (thumbnail data URI, {src, w, h} of the high-resolution file, original size).
    The high-resolution file is named by a hash of the original, so an unchanged photo is not re-encoded."""
    base = re.sub(r"=[^=/]*$", "", url)
    try:
        raw, _ = get(base + "=s0")  # =s0 asks Google for the original size
    except Exception:
        raw, _ = get(base + "=w4000")
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    name = f"{PHOTO_DIR}/{hashlib.sha1(raw).hexdigest()[:16]}.webp"
    path = os.path.join(out_dir, name)
    big = im.copy()
    big.thumbnail((PHOTO_MAX, PHOTO_MAX), Image.LANCZOS)
    if not os.path.exists(path):
        open(path, "wb").write(webp_bytes(big, PHOTO_QUALITY))
    small = im.resize((IMG_WIDTH, round(im.height * IMG_WIDTH / im.width)), Image.LANCZOS) if im.width > IMG_WIDTH else im
    return "data:image/webp;base64," + base64.b64encode(webp_bytes(small, WEBP_QUALITY)).decode(), {"src": name, "w": big.width, "h": big.height}, im.size


def main(page="index.html", out_dir="."):
    raw, ctype = get(SHEET + "/export?format=csv&gid=0")
    text = raw.decode("utf-8")
    if "csv" not in ctype or text.lstrip().startswith("<"):
        sys.exit("Sheet did not return CSV (probably no longer shared by link). Nothing published.")
    allrows = list(csv.reader(io.StringIO(text)))
    cols = allrows[0]
    # CSV row index i corresponds to sheet row i + 1; keep that link while dropping blank rows.
    kept = [(i + 1, r) for i, r in enumerate(allrows[1:], start=1) if any(c.strip() for c in r)]
    if not kept:
        sys.exit("Sheet has no data rows. Nothing published.")

    html_view, _ = get(SHEET + "/htmlview/sheet?headers=true&gid=0")
    title = sheet_title()
    parser = SheetImages()
    parser.feed(html_view.decode("utf-8", "replace"))

    jobs = {k: parser.images[sheet_row] for k, (sheet_row, _) in enumerate(kept) if sheet_row in parser.images}
    os.makedirs(os.path.join(out_dir, PHOTO_DIR), exist_ok=True)
    images, photos, sizes = {}, {}, []
    with ThreadPoolExecutor(8) as pool:
        for k, res in zip(jobs, pool.map(lambda u: _safe(photo, u, out_dir), jobs.values())):
            if res:
                images[str(k)], photos[str(k)], size = res
                sizes.append(size)
    # Drop high-resolution files no longer used by any row.
    keep = {os.path.basename(p["src"]) for p in photos.values()}
    for f in os.listdir(os.path.join(out_dir, PHOTO_DIR)):
        if f not in keep:
            os.remove(os.path.join(out_dir, PHOTO_DIR, f))

    data = {
        "synced": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "columns": cols,
        "rows": [r + [""] * (len(cols) - len(r)) for _, r in kept],
        "images": len(images),
        "photos": photos,
        "sheet": SHEET + "/edit?usp=sharing",
        "sheetTitle": title,
    }
    blob = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    html = open(page, encoding="utf-8").read()
    pattern = r'(<script type="application/json" id="flower-data">)(.*?)(</script>)'
    if not re.search(pattern, html, re.S):
        sys.exit("Page has no flower-data block. Nothing published.")
    html = re.sub(pattern, lambda m: m.group(1) + blob + m.group(3), html, count=1, flags=re.S)

    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, os.path.basename(page)), "w", encoding="utf-8").write(html)
    json.dump(images, open(os.path.join(out_dir, "images.json"), "w"), separators=(",", ":"))
    print(f"{len(cols)} columns, {len(kept)} rows, {len(images)} images "
          f"({os.path.getsize(os.path.join(out_dir, 'images.json')) // 1024} KB thumbnails)")
    if sizes:
        widths = sorted(w for w, _ in sizes)
        print(f"originals {widths[0]}-{widths[-1]}px wide (median {widths[len(widths) // 2]}); photos/ "
              f"{sum(os.path.getsize(os.path.join(out_dir, PHOTO_DIR, f)) for f in keep) // 1024} KB")


def sheet_title():
    """The spreadsheet's name, or "" if Google doesn't say."""
    try:
        page, _ = get(SHEET + "/htmlview")
        m = re.search(r'property="og:title" content="([^"]*)"', page.decode("utf-8", "replace"))
        return html_lib.unescape(m.group(1)).strip() if m else ""
    except Exception:
        return ""


def _safe(fn, arg, *rest):
    try:
        return fn(arg, *rest)
    except Exception as e:
        print("image failed:", arg[:80], e, file=sys.stderr)
        return None


if __name__ == "__main__":
    main(*sys.argv[1:3])
