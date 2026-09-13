"""Export only reviewed source paths, never local device configuration or evidence.

SPDX-License-Identifier: MIT
"""
from pathlib import Path, PurePosixPath


def source_paths(root):
    root = Path(root).resolve()
    paths = []
    seen = set()
    for name in (root / "source-files.txt").read_text().splitlines():
        if not name or name.startswith("#"):
            continue
        relative = PurePosixPath(name)
        if (relative.is_absolute() or ".." in relative.parts or
                str(relative) != name or name in seen):
            raise ValueError("Invalid or duplicate source path: " + name)
        seen.add(name)
        path = root.joinpath(*relative.parts)
        if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents) if p != root and root in p.parents):
            raise ValueError("Source must be a regular file without symlink ancestors: " + name)
        if not path.resolve().is_relative_to(root):
            raise ValueError("Source escapes root: " + name)
        if relative.name == "device.json" or set(relative.parts) & {"evidence", "private", "build", "__pycache__"}:
            raise ValueError("Private or generated source path: " + name)
        paths.append((name, path))
    return paths


def add_project_sources(archive, root):
    # Validate the complete list before adding anything to the archive.
    for name, path in source_paths(root):
        info = archive.gettarinfo(str(path), arcname="printer-modernization/" + name)
        # Local account names/IDs and modification dates are not source metadata.
        info.uid = info.gid = info.mtime = 0
        info.uname = info.gname = ""
        with path.open("rb") as source:
            archive.addfile(info, source)
