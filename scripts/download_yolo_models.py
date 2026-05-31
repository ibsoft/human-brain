#!/usr/bin/env python3
import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_MODELS = ["yolov8n.pt", "yolov8s.pt", "yolov8m.pt", "yolov8l.pt", "yolov8x.pt"]
DEFAULT_BASE_URL = "https://github.com/ultralytics/assets/releases/download/v8.2.0"


def parse_args():
    parser = argparse.ArgumentParser(description="Download Ultralytics YOLO model files if they do not already exist.")
    parser.add_argument(
        "models",
        nargs="*",
        default=DEFAULT_MODELS,
        help="Model filenames to download. Defaults to the standard YOLOv8 model set.",
    )
    parser.add_argument(
        "--dir",
        default="models",
        help="Directory for relative model filenames. Defaults to ./models.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Base URL for model assets.",
    )
    parser.add_argument("--force", action="store_true", help="Redownload models even when files already exist.")
    parser.add_argument("--timeout", type=int, default=120, help="Download timeout in seconds.")
    return parser.parse_args()


def destination_for(model_name, model_dir):
    path = Path(model_name).expanduser()
    if path.is_absolute() or path.parent != Path("."):
        return path
    return model_dir / path.name


def download(url, destination, timeout):
    tmp = destination.with_suffix(destination.suffix + ".part")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if tmp.exists():
        tmp.unlink()
    with urllib.request.urlopen(url, timeout=timeout) as response, tmp.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    tmp.replace(destination)


def main():
    args = parse_args()
    model_dir = Path(args.dir).expanduser()
    failures = []

    for model_name in args.models:
        destination = destination_for(model_name, model_dir)
        if destination.exists() and not args.force:
            print(f"skip {destination} (already exists)")
            continue

        filename = destination.name
        url = f"{args.base_url.rstrip('/')}/{filename}"
        print(f"download {filename} -> {destination}", flush=True)
        try:
            download(url, destination, args.timeout)
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            failures.append((filename, exc))
            print(f"failed {filename}: {exc}", file=sys.stderr)

    if failures:
        print("\nSome models were not downloaded:", file=sys.stderr)
        for filename, exc in failures:
            print(f"- {filename}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
