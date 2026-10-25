"""The privacy guard flags values without echoing them."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("privacy_guard", Path(__file__).resolve().parents[2] / "scripts/check_privacy.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_sensitive_patterns_detected_without_repeating_values():
    samples = ["/"+"home/fictional/person.json", "name"+"@private.invalid-domain.com", "gh"+"p_"+"x"*30]
    for sample in samples:
        findings = module.scan_text(sample)
        assert findings
        assert sample not in repr(findings)


def test_example_addresses_and_public_urls_allowed():
    assert module.scan_text("person@example.com https://github.com/example/project") == []


def test_staged_scan_reads_index_even_if_working_file_is_removed(tmp_path):
    import subprocess
    import sys
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    value = "person" + "@private.invalid-domain.com"
    private = tmp_path / "notes.txt"
    private.write_text(value)
    subprocess.run(["git", "-C", str(tmp_path), "add", "notes.txt"], check=True)
    private.unlink()
    result = subprocess.run([sys.executable, spec.origin, "--root", str(tmp_path), "--staged"], capture_output=True, text=True)
    assert result.returncode == 1
    assert "email address" in result.stderr
    assert value not in result.stderr + result.stdout
