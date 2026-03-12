from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from urllib import error, request


DEFAULT_API_URL = "https://content-receiver.replit.app/api/upload-content"
DEFAULT_SOURCE_DIR = Path.home() / "Desktop"


def is_hidden(relative_path: Path) -> bool:
    return any(part.startswith(".") for part in relative_path.parts)


def upload_file(url: str, source_file: Path, filename: str) -> str:
    payload = {
        "filename": filename,
        "content_base64": base64.b64encode(source_file.read_bytes()).decode("ascii"),
    }

    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with request.urlopen(req) as response:
        return response.read().decode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload all files from a local folder, including subfolders, to the upload-content API."
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_API_URL,
        help="Target upload-content API URL.",
    )
    parser.add_argument(
        "--folder",
        default=str(DEFAULT_SOURCE_DIR),
        help="Local folder whose files will be uploaded recursively.",
    )
    args = parser.parse_args()

    source_dir = Path(args.folder).expanduser()
    if not source_dir.exists():
        raise SystemExit(f"Folder does not exist: {source_dir}")
    if not source_dir.is_dir():
        raise SystemExit(f"Path is not a folder: {source_dir}")

    source_files = sorted(path for path in source_dir.rglob("*") if path.is_file())
    if not source_files:
        raise SystemExit(f"No files found in folder: {source_dir}")

    uploaded_count = 0
    skipped_count = 0
    failed_count = 0

    for source_file in source_files:
        relative_path = source_file.relative_to(source_dir)
        filename = relative_path.as_posix()

        if is_hidden(relative_path):
            skipped_count += 1
            print(f"Skipping hidden file: {filename}")
            continue

        try:
            response_body = upload_file(args.url, source_file, filename)
            uploaded_count += 1
            print(f"{filename}: {response_body}")
        except error.HTTPError as exc:
            failed_count += 1
            error_body = exc.read().decode("utf-8", errors="replace")
            print(f"{filename}: HTTP {exc.code} {exc.reason}")
            if error_body:
                print(error_body)
        except (error.URLError, OSError) as exc:
            failed_count += 1
            print(f"{filename}: {exc}")

    print(
        f"Completed. Uploaded: {uploaded_count}, skipped: {skipped_count}, failed: {failed_count}"
    )
    if failed_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
