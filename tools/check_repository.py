"""Offline release checks; not a substitute for the HACS validator or HA runtime."""
import ast
import json
from pathlib import Path
import re

ROOT_FILES = {".gitignore", "README.md", "README.cs.md", "LICENSE", "CHANGELOG.md", "hacs.json"}
ROOT_DIRS = {"custom_components", "tests", "tools", ".github"}


def public_files(root):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.suffix in (".pyc", ".zip"):
            continue
        if relative.parts[0] in ROOT_DIRS or relative.as_posix() in ROOT_FILES:
            yield path


def keys(value, prefix=""):
    result = set()
    for key, item in value.items():
        result.add(prefix + "." + key)
        if isinstance(item, dict):
            result |= keys(item, prefix + "." + key)
    return result


def validate(root):
    component = root / "custom_components" / "beny_modbus"
    assert [p.name for p in (root / "custom_components").iterdir() if p.is_dir() and p.name != "__pycache__"] == ["beny_modbus"]
    manifest = json.loads((component / "manifest.json").read_text(encoding="utf-8"))
    required = {"domain", "name", "version", "documentation", "issue_tracker", "codeowners"}
    assert required <= manifest.keys()
    assert manifest["domain"] == "beny_modbus"
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])
    assert manifest["codeowners"] == ["@Koubkovi7"]
    hacs = json.loads((root / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["homeassistant"] == "2026.10.0"
    assert not hacs.get("content_in_root", False)
    assert not hacs.get("zip_release", False)
    english = json.loads((component / "strings.json").read_text(encoding="utf-8"))
    for lang in ("en", "cs"):
        translated = json.loads((component / "translations" / f"{lang}.json").read_text(encoding="utf-8"))
        assert keys(translated) == keys(english), f"Translation structure differs: {lang}"
        for step in ("user", "reconfigure"):
            fields = translated["config"]["step"][step]
            assert fields["data"].keys() == fields["data_description"].keys()
            assert "4800" in fields["description"] and "502" in fields["description"]
    assert json.loads((component / "translations/en.json").read_text(encoding="utf-8")) == english
    constants = ast.parse((component / "const.py").read_text(encoding="utf-8"))
    version = next(ast.literal_eval(n.value) for n in constants.body
                   if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in n.targets))
    assert version == manifest["version"]
    for file in public_files(root):
        if file.suffix == ".py":
            ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        elif file.suffix == ".json":
            json.loads(file.read_text(encoding="utf-8"))
        if file.suffix in (".py", ".json", ".md", ".yml"):
            text = file.read_text(encoding="utf-8")
            assert not re.search(r"\b192\.168\.\d{1,3}\.\d{1,3}\b", text), f"Private address in {file}"
            assert not re.search(r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}", text), f"MAC address in {file}"
    assert (root / "LICENSE").is_file() and (root / "README.cs.md").is_file()
    return manifest


if __name__ == "__main__":
    result = validate(Path(__file__).resolve().parents[1])
    print(f"Repository checks passed for BENY Modbus {result['version']}")
