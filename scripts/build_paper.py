"""Regenerate checked tables and build the Chinese paper with XeLaTeX/BibTeX.

Uses argv lists (no shell), project-local intermediates, and no global TeX config.
The direct engine sequence avoids latexmk's optional Perl dependency on Windows.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path, log: Path, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    log.write_text(result.stdout, encoding="utf-8")
    if result.returncode:
        print(result.stdout[-10000:])
        raise SystemExit(f"Build failed ({result.returncode}); see {log}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-tables", action="store_true", help="Use already generated tables")
    args = parser.parse_args()
    build = ROOT / "tmp/paper-build"
    output = ROOT / "output/pdf"
    build.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    if not args.skip_tables:
        run([sys.executable, str(ROOT / "scripts/build_paper_tables.py")], ROOT, build / "tables.log")
    xelatex, bibtex = shutil.which("xelatex"), shutil.which("bibtex8") or shutil.which("bibtex")
    if not xelatex or not bibtex:
        raise SystemExit("XeLaTeX and BibTeX must be available on PATH (TeX Live or MiKTeX).")
    version = subprocess.check_output([xelatex, "--version"], text=True, errors="replace").splitlines()[0]
    miktex = "MiKTeX" in version
    command = [xelatex, "-interaction=nonstopmode", "-halt-on-error",
               "-disable-write18" if miktex else "-no-shell-escape",
               f"-output-directory={build}", "main.tex"]
    run(command, ROOT / "paper", build / "xelatex-1.log")
    env = os.environ.copy()
    env["BIBINPUTS"] = str(ROOT / "paper") + os.pathsep + env.get("BIBINPUTS", "")
    bib_command = [bibtex]
    if "bibtex8" in Path(bibtex).stem.lower():
        bib_command.append("--8bit")
    run(bib_command + ["main"], build, build / "bibtex.log", env)
    for index in (2, 3):
        run(command, ROOT / "paper", build / f"xelatex-{index}.log")
    log = (build / "main.log").read_text(encoding="utf-8", errors="replace")
    defects = [line for line in log.splitlines() if re.search(
        r"Overfull \\[hv]box|Missing character:|undefined|Rerun to get|Label\(s\) may have changed", line)]
    report = {"engine": version, "source": "paper/main.tex", "passes": 3,
              "bibliography": "BibTeX8/BibTeX / gbt7714-numeric", "layout_or_reference_warnings": defects}
    (build / "build-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if defects:
        print("\n".join(defects))
        raise SystemExit("Resolve layout/reference warnings before publishing the PDF.")
    target = output / "microgrid-paper.pdf"
    shutil.copy2(build / "main.pdf", target)
    print(f"Built {target}")
    print("No overfull boxes, missing characters or unresolved references. Visual review still required.")


if __name__ == "__main__":
    main()
