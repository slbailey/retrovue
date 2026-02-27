import json, pathlib

IN = pathlib.Path("docs/contracts/_migration/legacy_extraction.json")
OUT = pathlib.Path("docs/contracts/_migration/legacy_extraction_summary.md")

data = json.loads(IN.read_text(encoding="utf-8"))
lines = []
lines.append("# Legacy Extraction Summary")
lines.append("")
lines.append(f"Files scanned: **{data['count_files']}**")
lines.append("")
for f in sorted(data["files"], key=lambda x: x["file"]):
    lines.append(f"## {f['file']}")
    lines.append(f"- Bytes: {f['bytes']}")
    lines.append(f"- IDs found: {', '.join(f['rules_found']) if f['rules_found'] else '(none)'}")
    if f["must_lines_sample"]:
        lines.append("")
        lines.append("Sample MUST/MUST NOT lines:")
        for l in f["must_lines_sample"][:12]:
            lines.append(f"- {l}")
    lines.append("")
OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"Wrote {OUT}")
