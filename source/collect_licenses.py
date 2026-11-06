"""Collect installed dependency notices for the personal application bundle."""
from importlib import metadata
from pathlib import Path
import re
import shutil
import sys

destination = Path(sys.argv[1])
destination.mkdir(parents=True, exist_ok=True)
rows = ["ZTrans third-party dependencies", "", "This folder preserves upstream license and notice files from installed wheels.", "The original component licenses govern their respective components.", ""]
for distribution in sorted(metadata.distributions(), key=lambda d: d.metadata.get("Name", "").lower()):
    name = distribution.metadata.get("Name", "unknown")
    version = distribution.version
    component = destination / re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    license_value = distribution.metadata.get("License-Expression") or distribution.metadata.get("License", "See upstream notices")
    rows.append(f"{name} {version} — {license_value[:150]}")
    for resource in distribution.files or []:
        resource_path = Path(str(resource))
        if any(word in resource_path.name.lower() for word in ("license", "licence", "copying", "notice")) and resource_path.suffix.lower() in ("", ".txt", ".md", ".rst", ".html"):
            source = distribution.locate_file(resource)
            if source.is_file():
                component.mkdir(parents=True, exist_ok=True)
                target = component / "__".join(resource_path.parts[-3:])
                shutil.copy2(source, target)
(destination / "INDEX.txt").write_text("\n".join(rows), encoding="utf-8")
print(f"License notices collected: {len(rows) - 5} packages")
