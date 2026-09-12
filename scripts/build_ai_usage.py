"""Build the standalone AI usage disclosure without rebuilding the paper."""

from pathlib import Path
import shutil
import subprocess


def main():
    root = Path(__file__).resolve().parents[1]
    build = root / "tmp" / "ai-usage-build"
    build.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        subprocess.run(
            ["xelatex", "-interaction=nonstopmode", "-halt-on-error",
             f"-output-directory={build}", "ai-usage.tex"],
            cwd=root / "paper", check=True,
        )
    target = root / "outputs" / "deliverables" / "AI工具使用详情.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(build / "ai-usage.pdf", target)
    print(target)


if __name__ == "__main__":
    main()
