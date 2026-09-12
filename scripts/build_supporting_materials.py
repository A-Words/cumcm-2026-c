"""Package an explicit submission file list and verify every ZIP member."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "outputs/deliverables/supporting-materials.zip"
RECEIPT = ROOT / "outputs/verification/supporting-materials-validation.json"
COMPUTATION_SOURCES = (
    "scripts/prepare_data.py", "scripts/model.py", "scripts/solve.py",
    "scripts/solve_common.py", "scripts/q1.py", "scripts/q2.py",
    "scripts/q3.py", "scripts/q4.py",
    "scripts/feedback.py", "scripts/external_inputs.py", "scripts/evaluate_round2.py",
    "scripts/evaluate_paper_sensitivity.py", "scripts/export_results.mjs",
)
VALIDATION_SOURCES = (
    "scripts/validate_results.py", "scripts/validate_revision.py", "scripts/verify_q1_milp.py",
    "scripts/validate_round2.py", "scripts/validate_paper_sensitivity.py",
)
WORKBOOKS = ("result1.xlsx", "result2.xlsx", "result3.xlsx", "result4-2.xlsx", "result4-3.xlsx")


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def collect_files() -> dict[str, Path]:
    files = {name: ROOT / name for name in (*COMPUTATION_SOURCES, *VALIDATION_SOURCES)}
    for name in WORKBOOKS:
        files[name] = ROOT / "outputs/deliverables" / name
    for path in files.values():
        if not path.is_file():
            raise RuntimeError(f"Required supporting file is missing: {path}")
    return dict(sorted(files.items()))


def paper_manifest() -> dict:
    report = json.loads((ROOT / "outputs/verification/paper-validation.json").read_text(encoding="utf-8"))
    pdf = ROOT / report["pdf"]
    if report["status"] != "passed" or digest(pdf.read_bytes()) != report["pdf_sha256"]:
        raise RuntimeError("Build and validate the current paper before packaging.")
    for name, expected_hash in report["paper_source_sha256"].items():
        if digest((ROOT / name).read_bytes()) != expected_hash:
            raise RuntimeError(f"Paper source changed after validation: {name}; rebuild and validate.")
    sources = report["build"]["appendix_sources"]
    if not sources:
        raise RuntimeError("The paper has no recorded computation source listings.")
    for name, entry in sources.items():
        content = (ROOT / name).read_bytes()
        if digest(content) != entry["sha256"]:
            raise RuntimeError(f"Paper source listing is stale: {name}; rebuild the paper.")
    return {
        "schema_version": 3,
        "paper": {"filename": pdf.name, "sha256": report["pdf_sha256"], "pages": report["pages"]},
        "appendix_sources": sources,
        "selection": {
            "computation_sources": list(COMPUTATION_SOURCES),
            "validation_sources": list(VALIDATION_SOURCES),
            "workbooks": list(WORKBOOKS),
        },
        "note": "Current package contains only source programs and five result workbooks. Verification records remain in the workspace.",
    }


def verify(archive_path: Path, files: dict[str, Path], expected: dict) -> dict:
    with ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(files):
            raise RuntimeError("ZIP contains missing, duplicate or unexpected members.")
        hashes = {}
        for name, path in files.items():
            content = archive.read(name)  # Reading also checks the ZIP CRC.
            hashes[name] = {"sha256": digest(content), "bytes": len(content)}
            if content != path.read_bytes():
                raise RuntimeError(f"ZIP content differs from the current supporting file: {name}")
        total_bytes = sum(entry["bytes"] for entry in hashes.values())
    return {
        "status": "passed", "archive": ARCHIVE.relative_to(ROOT).as_posix(),
        "archive_sha256": digest(archive_path.read_bytes()), "archive_bytes": archive_path.stat().st_size,
        "file_count": len(files), "source_and_result_bytes": total_bytes, "members": names,
        "files": hashes, "selection": expected["selection"],
        "paper": expected["paper"], "appendix_sources": expected["appendix_sources"],
        "all_members_match_workspace": True, "zip_crc_checked": True,
        "workbooks": list(WORKBOOKS),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Verify the existing ZIP without rebuilding")
    args = parser.parse_args()
    files, expected = collect_files(), paper_manifest()
    if args.verify:
        report = verify(ARCHIVE, files, expected)
    else:
        temporary = ROOT / "tmp/supporting-materials.zip"
        temporary.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
            for name, path in files.items():
                archive.writestr(name, path.read_bytes())
        report = verify(temporary, files, expected)
        ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(ARCHIVE)
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({key: report[key] for key in ("status", "archive", "file_count", "archive_bytes")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
