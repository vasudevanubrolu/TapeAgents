"""Generate the code reference pages."""

from pathlib import Path

import mkdocs_gen_files

project = "tapeagents"
nav = mkdocs_gen_files.Nav()
root = Path(__file__).parent.parent
src = root / project

for path in sorted(src.rglob("*.py")):
    module_path = path.relative_to(src).with_suffix("")
    doc_path = path.relative_to(src).with_suffix(".md")
    full_doc_path = Path("reference", doc_path)

    parts = tuple(module_path.parts)

    if parts[-1] == "__init__":
        continue
    elif parts[-1] == "__main__":
        continue
    elif not doc_path:
        continue

    nav[parts] = doc_path.as_posix()

    with mkdocs_gen_files.open(full_doc_path, "w") as fd:
        identifier = ".".join(parts)
        if identifier:
            print(f"::: {project}." + identifier, file=fd)

    mkdocs_gen_files.set_edit_path(full_doc_path, path.relative_to(root))
