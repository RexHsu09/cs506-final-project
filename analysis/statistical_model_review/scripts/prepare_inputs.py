"""Extract the exact supplied archive, verify hashes, and leave sources unchanged."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SHA256 = "de21dc73d63bbe0f8e08c270281407a3cb94a8828f3c59af8c010466abc549d3"
EXPECTED_FILES = {
    "roads_initial_clean_attributes.csv", "crashes_clean.csv", "segment_labels.csv",
    "model_features.csv", "segment_split.csv", "model_a_test_predictions.csv", "model_a_results.csv"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    archive_hash = hashlib.sha256(args.archive.read_bytes()).hexdigest()
    if archive_hash != EXPECTED_SHA256:
        raise ValueError("This review expects Bryan's 24 November archive; hash mismatch.")
    destination = ROOT / "data/raw/bryan"
    with zipfile.ZipFile(args.archive) as archive:
        if set(archive.namelist()) != EXPECTED_FILES or len(archive.infolist()) != 7:
            raise ValueError("Unexpected archive contents.")
        if sum(x.file_size for x in archive.infolist()) > 100_000_000 or archive.testzip():
            raise ValueError("Invalid or unexpectedly large archive.")
        blobs = {name: archive.read(name) for name in sorted(EXPECTED_FILES)}
    # Refuse to replace an existing different source table.
    for name, blob in blobs.items():
        path = destination / name
        if path.exists() and path.read_bytes() != blob:
            raise FileExistsError(f"Existing source differs: {path}")
    destination.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, blob in blobs.items():
        (destination / name).write_bytes(blob)
        files[name] = {"bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()}
    manifest = {"source": "User-supplied Bryan model archive", "archive_name": args.archive.name,
                "archive_sha256": archive_hash, "files": files}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Verified seven unchanged source tables: {destination}")


if __name__ == "__main__":
    main()
