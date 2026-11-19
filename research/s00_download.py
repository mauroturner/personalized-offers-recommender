"""Download UCI Online Retail II (CC BY 4.0) into data/raw/, verified by size and SHA-256.

Source: https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip (the same zip project 04 uses).
The licence is read from the dataset's UCI page, which is saved next to the zip and checked for the
licence sentence. Only the workbook member is extracted, by its exact name, after the zip is verified.
Standard library only, no account, no token.
Run from any directory:  python -I research/s00_download.py
"""
import hashlib
import json
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
RAW = PROJECT / "data" / "raw"
ZIP_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
PAGE_URL = "https://archive.ics.uci.edu/dataset/502/online+retail+ii"
ZIP_NAME = "online_retail_ii.zip"
ZIP_BYTES = 45622418
ZIP_SHA256 = "572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb"
MEMBER = "online_retail_II.xlsx"
LICENCE_SENTENCE = "This dataset is licensed under a"
LICENCE_NAME = "(CC BY 4.0) license"
UA = "research-script/1.0"


def fetch(url, dest):
    """Stream url into dest through a temporary name, then rename. Returns the byte count."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    total = 0
    with urllib.request.urlopen(req, timeout=300) as resp, open(tmp, "wb") as out:
        while True:
            block = resp.read(1 << 20)
            if not block:
                break
            out.write(block)
            total += len(block)
    tmp.replace(dest)
    return total


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    zip_path = RAW / ZIP_NAME
    if zip_path.exists() and zip_path.stat().st_size == ZIP_BYTES and sha256_of(zip_path) == ZIP_SHA256:
        print("[skip] zip already present and verified")
    else:
        n = fetch(ZIP_URL, zip_path)
        print(f"[get ] {ZIP_NAME}: {n} bytes")
    size = zip_path.stat().st_size
    digest = sha256_of(zip_path)
    zip_ok = size == ZIP_BYTES and digest == ZIP_SHA256
    print(f"[check] zip bytes {size} (expected {ZIP_BYTES}), sha256 {'match' if digest == ZIP_SHA256 else 'MISMATCH'}")
    if not zip_ok:
        print("VERIFICATION FAILED: the zip is not the pinned file; nothing extracted")
        return 2

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        print(f"[zip ] members: {names}")
        if MEMBER not in names:
            print(f"VERIFICATION FAILED: member {MEMBER} is missing")
            return 2
        xlsx = RAW / MEMBER
        xlsx.write_bytes(zf.read(MEMBER))
    xlsx_sha = sha256_of(xlsx)
    print(f"[xlsx] {MEMBER}: {xlsx.stat().st_size} bytes, sha256 {xlsx_sha}")

    page = RAW / "uci_dataset_page.html"
    fetch(PAGE_URL, page)
    text = page.read_text(encoding="utf-8", errors="replace")
    licence_ok = LICENCE_SENTENCE in text and LICENCE_NAME in text
    print(f"[licence] UCI page states CC BY 4.0: {'yes' if licence_ok else 'NOT FOUND'}")

    manifest = {
        "dataset": "UCI Online Retail II (Daqing Chen), doi 10.24432/C5CG6D",
        "zip": {"path": f"data/raw/{ZIP_NAME}", "source": ZIP_URL, "bytes": size, "sha256": digest,
                "verified": zip_ok},
        "workbook": {"member": MEMBER, "path": f"data/raw/{MEMBER}", "bytes": xlsx.stat().st_size,
                     "sha256": xlsx_sha},
        "licence": "CC BY 4.0" if licence_ok else "unverified",
        "licence_source": PAGE_URL,
        "licence_page": {"path": "data/raw/uci_dataset_page.html", "bytes": page.stat().st_size,
                         "sha256": sha256_of(page)},
        "downloaded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (RAW / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    ok = zip_ok and licence_ok
    print("all files verified" if ok else "VERIFICATION INCOMPLETE")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
