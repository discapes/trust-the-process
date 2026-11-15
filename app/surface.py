"""Deterministic rules over the diff. Each signal names the rule, the hunks it fired on and, for decisions the AI never
makes, the question for the owner. The rules are plain pattern matches so a person can read and dispute them."""
import re

# Assemblies other projects consume. The source generator and analyzers run in the compiler, so their types are not API.
SHIPPED = re.compile(r"^src/(MessagePack|MessagePack\.Annotations|MessagePack\.AspNetCoreMvcFormatter|MessagePack\.Experimental)/")
RUNTIME = re.compile(r"^src/MessagePack/")  # serializes and deserializes untrusted input at run time
PUBLIC_TYPE = re.compile(r"^\+\s*public\s+(?:(?:sealed|static|abstract|partial|readonly)\s+)*(class|struct|interface|enum|record|delegate)\s+(\w+)")
PUBLIC_MEMBER = re.compile(r"^\+\s*public\s+(?!class|struct|interface|enum|record|delegate)[\w<>\[\]?,. ]+?\s+(\w+)\s*(?:\{|\(|=|;)")
RELEASE_ROW = re.compile(r"^\+\s*(MsgPack\d+)\s*\|\s*(\w+)\s*\|\s*(\w+)")
SEVERITY = re.compile(r"^([+-]).*(?:defaultSeverity:|DiagnosticSeverity\.)\s*(?:DiagnosticSeverity\.)?(\w+)")


def added(h):
    return [l for l in h["lines"] if l[0] == "+"]


def signals(hunks):
    out = []

    def fire(rule, hs, detail, question=None):
        out.append({"rule": rule, "hunks": list(dict.fromkeys(h["id"] for h in hs)), "paths": sorted({h["path"] for h in hs}),
                    "detail": detail, "question": question})

    api = [(h, m) for h in hunks if h["kind"] == "source" and SHIPPED.match(h["path"])
           for l in added(h) for m in [PUBLIC_TYPE.match(l) or PUBLIC_MEMBER.match(l)] if m]
    api_files = [h for h in hunks if re.search(r"PublicAPI\.(Shipped|Unshipped)\.txt$", h["path"])]
    if api or api_files:
        names = sorted({m.group(m.lastindex) for _, m in api})
        fire("public-api", [h for h, _ in api] + api_files, "New public API in a shipped assembly: " + ", ".join(names),
             "Approve the shape of the new public API (" + ", ".join(names) + "). Public API cannot change after release "
             "without a breaking change.")

    rows = [(h, m) for h in hunks if h["path"].endswith("AnalyzerReleases.Unshipped.md") for l in added(h) for m in [RELEASE_ROW.match(l)] if m]
    if rows:
        ids = [f"{m[1]} ({m[3]})" for _, m in rows]
        fire("diagnostic-ids", [h for h, _ in rows], "New diagnostics: " + ", ".join(ids),
             "Approve the new diagnostic IDs, titles and severities (" + ", ".join(ids) + "). IDs are permanent once released.")

    for h in hunks:
        sev = {sign: s for l in h["lines"] for m in [SEVERITY.match(l)] if m for sign, s in [m.groups()]}
        if "-" in sev and "+" in sev and sev["-"] != sev["+"]:
            fire("severity-change", [h], f"Diagnostic severity changed from {sev['-']} to {sev['+']} in {h['path']}",
                 f"Approve lowering or raising a diagnostic's severity ({sev['-']} to {sev['+']}).")

    deps = [h for h in hunks if h["kind"] == "build" and any(re.search(r"<(PackageReference|PackageVersion) ", l) for l in added(h))]
    if deps:
        fire("dependency", deps, "Package references added", "Approve the new dependencies and their licences.")

    runtime = [h for h in hunks if RUNTIME.match(h["path"])]
    if runtime:
        fire("runtime-deserialization", runtime, "Changes code that deserializes untrusted input at run time",
             "Confirm the security posture of the runtime change; the reviewer does not judge deserialization security.")

    skipped = [h for h in hunks if h["kind"] == "test" and any(re.search(r"Skip\s*=", l) for l in added(h))]
    removed_tests = [h for h in hunks if h["kind"] == "test"
                     and sum(bool(re.search(r"\[(Fact|Theory)", l)) for l in h["lines"] if l[0] == "-")
                     > sum(bool(re.search(r"\[(Fact|Theory)", l)) for l in added(h))]
    if skipped or removed_tests:
        fire("tests-weakened", skipped + removed_tests, "Tests skipped or removed")

    suppress = [h for h in hunks if any(re.search(r"#pragma warning disable|\[SuppressMessage|<NoWarn>", l) for l in added(h))]
    if suppress:
        fire("warnings-suppressed", suppress, "Compiler or analyzer warnings suppressed")
    return out


def facts(hunks, clusters):
    """Scoped statements the rules can make with certainty, shown as checked claims of the reviewer itself."""
    out = []
    if not any(RUNTIME.match(h["path"]) for h in hunks) and not any(RUNTIME.match(f) for c in clusters for f in c["files"]):
        out.append("No file of the runtime library (src/MessagePack/), which deserializes untrusted input, is changed.")
    if not any(h["kind"] == "build" for h in hunks):
        out.append("No project, package or build file is changed.")
    return out
