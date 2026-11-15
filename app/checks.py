"""Machine checks run on the Verda instance: full suite and fail-before for a ref, per-claim reverts and probe tests."""
import re
import shlex
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import failbefore
import partition
import remote

JOBS = ThreadPoolExecutor(2)  # the instance has 4 cores; two builds at a time keep each one reasonably fast


def suite(name, ref):
    """Full build and suite at the ref, plus the run with its src/ changes reverted; returns the fail-before comparison."""
    if not remote.has("base"):
        remote.run("/root/suite.sh base 32258fdb")
    if not remote.has(name):
        remote.run(f"/root/suite.sh {name} {shlex.quote(ref)}")
    if not remote.has(f"{name}-revert"):
        remote.run(f"/root/revert_src.sh {name}-revert {shlex.quote(ref)}")
    base, head, rev = (remote.fetch(n) for n in ("base", name, f"{name}-revert"))
    return failbefore.compare(base, head, rev) | {"suite_passed": "test exit 0" in (head / "test.log").read_text()}


def patch(hunks):
    """A patch with just these hunks, to revert them (git apply -R) on top of the ref."""
    out = []
    for path in dict.fromkeys(h["path"] for h in hunks):
        hs = [h for h in hunks if h["path"] == path]
        new = hs[0]["old_start"] == 0
        out += [f"diff --git a/{path} b/{path}"] + (["new file mode 100644", "--- /dev/null"] if new else [f"--- a/{path}"]) + [f"+++ b/{path}"]
        for h in hs:
            old = sum(l[0] in " -" for l in h["lines"])
            cur = sum(l[0] in " +" for l in h["lines"])
            out.append(f"@@ -{h['old_start']},{old} +{h['new_start']},{cur} @@")
            out += h["lines"]
    return "\n".join(out) + "\n"


def projects(ref, tests):
    """Test project directories (under tests/) that declare the classes of these tests."""
    out = set()
    for cls in {t.rsplit(".", 1)[0].rsplit(".", 1)[-1] for t in tests}:
        hits = partition.git("grep", "-l", "-E", rf"class {cls}\b", ref, "--", "tests/").split("\n")
        out |= {h.split(":", 1)[1].split("/")[1] for h in hits if h}
    return sorted(out)


def test_job(name, ref, filters, projs, revert=None, add=()):
    """Run the tests whose names contain one of `filters`, in these test projects, at the ref, after reverting the hunks
    in `revert` and adding files {file name: (project, text)}. Returns {"compiled", "outcomes": {test: outcome}, "log"}."""
    def job():
        patch_path = "-"
        if revert:
            patch_path = f"/root/patches/{name}.patch"
            remote.put(patch(revert), patch_path, text=True)
        adds = []
        for fname, (proj, text) in dict(add).items():
            remote.put(text, f"/root/probes/{name}/{fname}", text=True)
            adds.append(f"/root/probes/{name}/{fname}:tests/{proj}")
        filt = "|".join(f"FullyQualifiedName~{f}" for f in filters)
        remote.run(" ".join(shlex.quote(a) for a in ["/root/wt_test.sh", name, ref, filt, " ".join(projs), patch_path, *adds]))
        d = remote.fetch(name)
        log = (d / "test.log").read_text()
        outs = failbefore.outcomes(d)
        return {"compiled": bool(outs) and "patch failed" not in log,
                "outcomes": {t: o for t, o in outs.items() if any(f in t for f in filters)}, "log": tail(log)}
    return JOBS.submit(job)


def project_job(name, files):
    """Build a standalone probe project made of {file name: text}; returns {"built": bool, "log": tail}."""
    def job():
        remote.run(f"rm -rf /root/probes/{name}")
        for fname, text in files.items():
            remote.put(text, f"/root/probes/{name}/{fname}", text=True)
        remote.run(f"/root/project_build.sh {name}")
        log = (remote.fetch(name) / "build.log").read_text()
        return {"built": "build exit 0" in log, "log": tail(log)}
    return JOBS.submit(job)


def tail(log):
    """The informative end of a dotnet log: errors and failed-test messages, else its last lines."""
    keep = [l for l in log.split("\n") if re.search(r"error |Failed |Assert|Expected|Actual|Exception|Passed!|Failed!|build exit", l)]
    return "\n".join(dict.fromkeys(keep[:40])) or "\n".join(log.split("\n")[-15:])
