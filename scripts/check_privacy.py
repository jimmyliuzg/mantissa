"""Flag common private artifacts and credential/contact patterns before commits.

This is a guard, not proof that arbitrary financial data is anonymous. Review
sample data manually. Git identities, copyright and public repository URLs are
outside this content scan. Findings never print the matched private value.
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys

PATTERNS = {
    "absolute personal home path": re.compile(r"/(?:home|Users)/[A-Za-z0-9_.-]+"),
    "credential": re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|(?:AKIA|ASIA)[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{35}|glpat-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})"),
    "SSN-shaped identifier": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "email address": re.compile(r"[\w.+-]+@([\w.-]+\.[A-Za-z]{2,})"),
}
PRIVATE_FILE = re.compile(r"(?i)^(?:my_plan|mantissa_plan|planning_assumptions|personal_finances|account-statement|tax-return)\.(?:json|csv|xlsx|pdf|docx)$")
EXAMPLE_DOMAINS = {"example.com", "example.org", "example.net"}


def scan_text(text):
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        for label, pattern in PATTERNS.items():
            for match in pattern.finditer(line):
                if label == "email address" and (match.group(1).lower() in EXAMPLE_DOMAINS or match.group(1).lower().endswith((".test", ".invalid"))):
                    continue
                findings.append((number, label))
                break
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--staged", action="store_true", help="Inspect exact index contents, including new files")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        top = subprocess.check_output(["git", "-C", str(root), "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL).decode().strip()
    except subprocess.CalledProcessError:
        top = None
    if top == str(root):
        command = ["git", "-C", str(root), "ls-files", "-z", "--cached"]
        if not args.staged:
            command += ["--others", "--exclude-standard"]
        paths = sorted(set(filter(None, subprocess.check_output(command).decode().split("\0"))))
    elif args.staged:
        parser.error("--staged requires the repository root")
    else:
        excluded = {".git", "node_modules", ".venv", "dist", "__pycache__", ".pytest_cache"}
        paths = [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and not excluded.intersection(p.relative_to(root).parts)]
    errors = []
    checked = 0
    for relative in paths:
        path = root / relative
        if PRIVATE_FILE.match(path.name):
            errors.append(f"{relative}: private-plan/document filename")
        if args.staged:
            result = subprocess.run(["git", "-C", str(root), "show", ":" + relative], capture_output=True)
            if result.returncode:
                continue
            raw = result.stdout
        else:
            if not path.is_file() or path.is_symlink():
                continue
            raw = path.read_bytes()
        if b"\0" in raw:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeError:
            continue
        checked += 1
        errors.extend(f"{relative}:{line}: {label}" for line, label in scan_text(text))
    for error in errors:
        print(error, file=sys.stderr)
    print(f"Privacy content check: {checked} text files; {len(errors)} findings.")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
