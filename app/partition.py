"""Split a branch's diff into change units: hand-written hunks with IDs (H1, H2, ...) and generated files clustered by the
edit they share (G1, G2, ...), so a human reads one representative per cluster."""
import re
import subprocess
from collections import defaultdict
from pathlib import Path

REPO = str(Path.home() / "code/cloned/junction26-messagepack-csharp")


def git(*args, repo=REPO):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout


def kind(path, changed):
    if path.endswith(".g.cs") or "/Resources/" in path:
        return "generated"  # verified snapshots of source generator output
    if path.endswith(".cs") and path[:-3] + ".tt" in changed:
        return "generated"  # T4 output; the .tt next to it is the hand-written change
    if re.search(r"\.(csproj|props|targets)$|global\.json$", path):
        return "build"
    if path.startswith("tests/"):
        return "test"
    if path.endswith(".md"):
        return "doc"
    return "source"


def hunks_of(branch, path):
    """The file's diff hunks: header, start lines and the +/-/context lines."""
    out, cur = [], None
    for line in git("diff", "-U3", f"{branch}~1", branch, "--", path).split("\n"):  # keeps \r of CRLF files
        if m := re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)", line):
            cur = {"old_start": int(m[1]), "new_start": int(m[2]), "context": m[3].strip(), "lines": []}
            out.append(cur)
        elif cur is not None and line and line[0] in " +-" and not line.startswith(("+++", "---")):
            cur["lines"].append(line)
        elif cur is not None and line.startswith("\\"):
            continue  # "\ No newline at end of file"
    return out


def changed_lines(branch, path):
    """Distinct changed lines of one file, whitespace-trimmed, as '+line' / '-line'."""
    diff = git("diff", "-U0", f"{branch}~1", branch, "--", path)
    return {l[0] + l[1:].strip() for l in diff.splitlines() if l and l[0] in "+-" and not l.startswith(("+++", "---"))}


def partition(branch):
    stat = [l.split("\t") for l in git("diff", "--numstat", f"{branch}~1", branch).splitlines()]
    changed = {p for *_, p in stat}
    hunks, generated = [], []
    for added, removed, path in stat:
        k = kind(path, changed)
        if k == "generated":
            generated.append({"path": path, "added": int(added), "removed": int(removed)})
            continue
        for h in hunks_of(branch, path):
            h |= {"id": f"H{len(hunks) + 1}", "path": path, "kind": k,
                  "added": sum(l[0] == "+" for l in h["lines"]), "removed": sum(l[0] == "-" for l in h["lines"])}
            hunks.append(h)

    by_edit = defaultdict(list)
    for f in generated:
        by_edit[frozenset(changed_lines(branch, f["path"]))].append(f)
    clusters = []
    for edit, files in sorted(by_edit.items(), key=lambda kv: -len(kv[1])):
        rep = files[0]["path"]
        clusters.append({"id": f"G{len(clusters) + 1}", "edit": sorted(edit), "files": [f["path"] for f in files],
                         "representative": rep, "lines": sum(f["added"] + f["removed"] for f in files),
                         "diff": hunks_of(branch, rep)})
    return {"hunks": hunks, "clusters": clusters}
