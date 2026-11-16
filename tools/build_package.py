"""Build a portable public source/install ZIP from an explicit file allowlist."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from check_repository import public_files, validate


def build(destination=None):
    root = Path(__file__).resolve().parents[1]
    manifest = validate(root)
    version = manifest["version"].replace(".", "_")
    destination = Path(destination) if destination else root / "dist" / f"beny_modbus_v{version}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in public_files(root):
            archive.write(file, file.relative_to(root).as_posix())
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert "custom_components/beny_modbus/manifest.json" in names
        assert "hacs.json" in names
        assert not any(name.startswith(("docs/", ".git/", "dist/")) for name in names)
    print(json.dumps({
        "path": str(destination.resolve()), "version": manifest["version"],
        "bytes": destination.stat().st_size, "files": len(names),
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
    }, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    build(parser.parse_args().output)
