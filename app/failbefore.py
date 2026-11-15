"""Fail-before/pass-after from TRX results of three runs: the base commit, the branch head, and the branch with its src/
changes reverted (checks/revert_src.sh). Tests that pass at the head and fail when reverted exercise the change."""
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

RANK = {"Failed": 2, "Passed": 1}


def outcomes(run: Path) -> dict[str, str]:
    """Test method -> worst outcome of its cases over every TRX file of a run.
    Theory cases are merged because some carry random GUIDs and timestamps in their names."""
    out = {}
    for trx in run.glob("*.trx"):
        for r in ET.parse(trx).iter():
            if r.tag.endswith("UnitTestResult"):
                name, o = r.get("testName").split("(")[0], r.get("outcome")
                if RANK.get(o, 0) >= RANK.get(out.get(name), 0):
                    out[name] = o
    return out


def build_ok(run: Path) -> bool:
    return bool(re.search(r"^build exit 0$", (run / "build.log").read_text(), re.M))


def verdict(head: str, revert: str | None) -> str:
    if head != "Passed":
        return "fails at head"
    if revert is None:
        return "needs the change to compile"  # its project no longer compiles without the change
    return "exercises the change" if revert == "Failed" else "passes without the change"


def compare(base: Path, head: Path, revert: Path):
    b, h, r = outcomes(base), outcomes(head), outcomes(revert)
    tests = {t: verdict(h[t], r.get(t)) for t in sorted(set(h) - set(b))}
    return {
        "builds": {"base": build_ok(base), "head": build_ok(head), "revert": build_ok(revert)},
        "totals": {k: dict(Counter(o.values())) for k, o in (("base", b), ("head", h), ("revert", r))},
        "new_tests": tests,
        "regressions": sorted(t for t, o in b.items() if o == "Passed" and h.get(t) != "Passed"),
        "failing_at_head": sorted(t for t, o in h.items() if o == "Failed"),
        # Existing tests that depend on the change: the branch edited their expectations (e.g. verified snapshots).
        "existing_tests_exercising_change": sorted(t for t in b if h.get(t) == "Passed" and r.get(t) == "Failed"),
    }
