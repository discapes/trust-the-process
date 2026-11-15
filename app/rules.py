"""Everything after the models is deterministic: claim status from checks, refusals, review depth per change unit, the
list of what was not checked, and area tiers from the track record."""
import fnmatch
import hashlib
import json
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"
FULL_RULES = {"public-api", "diagnostic-ids", "severity-change", "dependency", "runtime-deserialization", "tests-weakened"}
DEPTHS = ["light", "standard", "full"]
SPOT_CHECK = 5  # one in five units the AI would clear gets a full human read, to measure what the reviewer misses


def claim_status(c, probes):
    """checked: reverting the claim's hunks makes a test fail. opinion: nothing machine-checked backs it.
    contradicted: an adversary probe reproduced a failure against it."""
    if any(p["result"] == "reproduced" and c["id"] in p.get("claims", []) for p in probes):
        return "contradicted"
    if c.get("revert") and c["revert"]["failing_tests"]:
        return "checked"
    return "opinion"


def refusals(signals, writer_questions, new_tests):
    out = [{"question": s["question"], "why": s["detail"], "source": f"rule {s['rule']}", "hunks": s["hunks"]}
           for s in signals if s["question"]]
    out += [{"question": q["question"], "why": q["why"], "source": "writer model", "hunks": q.get("hunks", [])} for q in writer_questions]
    idle = sorted(t for t, v in new_tests.items() if v == "passes without the change")
    if idle:
        out.append({"question": f"{len(idle)} of {len(new_tests)} new tests pass without the change, so the behaviour they test "
                                "already works at the base. Does the reported problem exist in this base, and what are these tests for?",
                    "why": "Tests that pass with the change reverted: " + ", ".join(idle), "source": "fail-before", "hunks": []})
    for i, r in enumerate(out, 1):
        r["id"] = f"R{i}"
    return out


def areas():
    return json.loads((DATA / "areas.json").read_text())


def area_of(path, area_list):
    return next((a for a in area_list if any(fnmatch.fnmatch(path, g) for g in a["globs"])), None)


def tier(area):
    """probation after an escape or a spot-check miss until 10 clean spot-checks follow it; trusted after 20 clean ones."""
    events = area.get("history", [])
    bad = [i for i, e in enumerate(events) if e["kind"] in ("escape", "spot-check miss")]
    clean_after = sum(e["kind"] == "clean spot-check" for e in events[(bad[-1] + 1 if bad else 0):])
    if bad and clean_after < 10:
        return "probation"
    return "trusted" if clean_after >= 20 else "standard"


def routing(hunks, clusters, claims, signals, probes, unexplained, refusals, sha, returned=None):
    """Review depth per unit (a file's hunks, or a generated cluster) and the rules that set it."""
    area_list = areas()
    by_hunk = {}
    for c in claims:
        for h in c["hunks"]:
            by_hunk.setdefault(h, []).append(c)
    sig_by_hunk = {}
    for s in signals:
        for h in s["hunks"]:
            sig_by_hunk.setdefault(h, []).append(s["rule"])
    units = []
    for path in dict.fromkeys(h["path"] for h in hunks):
        hs = [h for h in hunks if h["path"] == path]
        kind, lines = hs[0]["kind"], sum(h["added"] + h["removed"] for h in hs)
        depth, why, read = "light", [], 0
        rules = {r for h in hs for r in sig_by_hunk.get(h["id"], [])}
        if rules & FULL_RULES:
            depth, why = "full", [f"rule {r}" for r in sorted(rules & FULL_RULES)]
        if kind in ("source", "build") and any(h["id"] in unexplained for h in hs):
            depth = "full"
            why.append("hunks no claim explains: " + ", ".join(h["id"] for h in hs if h["id"] in unexplained))
        beyond = [h for h in hs if kind in ("source", "build") and h["id"] in by_hunk and not any(c["criteria"] for c in by_hunk[h["id"]])]
        if beyond:
            depth = "full"
            why.append("work beyond the requirement: " + ", ".join(sorted({c["id"] for h in beyond for c in by_hunk[h["id"]]})))
        contradicted = sorted({c["id"] for h in hs for c in by_hunk.get(h["id"], []) if c["status"] == "contradicted"})
        if contradicted:
            depth = "full"
            why.append("claims contradicted by a probe: " + ", ".join(contradicted))
        opinion = [h for h in hs if kind in ("source", "build") and h["id"] in by_hunk
                   and not any(c["status"] == "checked" for c in by_hunk[h["id"]])]
        if depth != "full" and opinion:
            depth = "standard"
            why.append("claims without a failing revert: " + ", ".join(sorted({c["id"] for h in opinion for c in by_hunk[h["id"]]})))
            read = sum(h["added"] + h["removed"] for h in opinion)
        asked = [(h, r["id"]) for h in hs for r in refusals if h["id"] in r["hunks"] and kind != "test"]
        if depth != "full" and asked:
            depth = "standard"
            why.append("needed to answer " + ", ".join(sorted({r for _, r in asked})))
            read += sum(h["added"] + h["removed"] for h in dict((h["id"], h) for h, _ in asked).values() if h not in opinion)
        if depth != "full" and "warnings-suppressed" in rules:
            depth = "standard"
            why.append("rule warnings-suppressed")
            read = max(read, sum(h["added"] + h["removed"] for h in hs if "warnings-suppressed" in sig_by_hunk.get(h["id"], [])))
        area = area_of(path, area_list)
        if area and tier(area) == "probation" and depth != "full":
            depth = DEPTHS[DEPTHS.index(depth) + 1]
            why.append(f"area {area['name']} is on probation")
        if depth == "light":
            why.append({"test": "tests: evidence for the claims", "doc": "documentation: read the claim card"}.get(kind, "every claim checked"))
            if int(hashlib.sha1(f"{sha}{path}".encode()).hexdigest(), 16) % SPOT_CHECK == 0:
                depth = "full"
                why = [f"spot-check sample (1 in {SPOT_CHECK} units the AI clears)"]
        read = 0 if depth == "light" else read if depth == "standard" and read else lines
        read_hunks = [] if depth == "light" else [h["id"] for h in hs] if read == lines else sorted(
            {h["id"] for h in opinion} | {h["id"] for h, _ in asked} | {h["id"] for h in hs if "warnings-suppressed" in sig_by_hunk.get(h["id"], [])})
        units.append({"unit": path, "kind": kind, "hunks": [h["id"] for h in hs], "lines": lines, "depth": depth,
                      "why": why, "read": read, "read_hunks": read_hunks, "area": area["name"] if area else None})
    templates = {h["path"] for h in hunks if h["path"].endswith(".tt")}
    for c in clusters:
        rep_lines = sum(sum(l[0] in "+-" for l in h["lines"]) for h in c["diff"])
        unit = {"unit": c["id"], "kind": "generated", "hunks": [], "lines": c["lines"], "area": "Generated code",
                "representative": c["representative"], "files": len(c["files"]), "read_hunks": []}
        if all(f[:-3] + ".tt" in templates for f in c["files"]):
            unit |= {"depth": "light", "read": 0, "why": ["T4 output of " + ", ".join(f.rsplit("/", 1)[-1][:-3] + ".tt" for f in c["files"])
                                                          + "; the template is the hand-written change"]}
        else:
            unit |= {"depth": "standard", "read": rep_lines,
                     "why": ["generated file with an edit of its own" if len(c["files"]) == 1 else
                             f"read one representative; the other {len(c['files']) - 1} files have the identical edit"]}
        units.append(unit)
    if returned:  # nobody reads a change that fails its own tests
        for u in units:
            u.update(depth="light", read=0, read_hunks=[], why=["returned to the agent: the suite fails"])
    total = sum(u["lines"] for u in units)
    read = sum(u["read"] for u in units)
    return {"units": units, "total_lines": total, "read_lines": read, "share": read / total if total else 0}


def checked(p):
    """What the machine, the rules and the adversary checked, as labelled groups of short rows."""
    fb, t = p["failbefore"], p["suite"]["totals"]["head"]
    exercising = sum(v == "exercises the change" for v in fb["new_tests"].values())
    tests = [{"text": f"Build and full suite {'pass' if p['suite']['passed'] else 'fail'}: {t.get('Passed', 0):,} test methods passed, "
                      f"{t.get('Failed', 0)} failed, {len(p['suite']['regressions'])} regressions against the base"},
             {"text": f"{exercising} of {len(fb['new_tests'])} new tests fail with the change reverted"
                      + (f"; {len(fb['existing_tests_exercising_change'])} existing tests depend on it" if fb["existing_tests_exercising_change"] else "")}]
    claims = []
    for c in p["claims"]:
        if c["status"] == "checked":
            n, hunks = len(c["revert"]["failing_tests"]), c["revert"]["hunks"]
            claims.append({"id": c["id"], "text": c["summary"], "detail": f"{n} test{' fails' if n == 1 else 's fail'} when "
                           f"{', '.join(hunks)} {'is' if len(hunks) == 1 else 'are'} reverted"})
    survived = [{"id": x["id"], "text": x["title"]} for x in p["probes"] if x["result"] == "not reproduced"]
    return [g for g in (
        {"label": "Build and tests", "items": tests},
        {"label": "Claims checked by revert", "items": claims},
        {"label": "Rule checks", "items": [{"text": f.rstrip(".")} for f in p["facts"]]},
        {"label": "Probes the change survived", "note": "Attacks that failed to show a defect; they do not show that none exists.",
         "items": survived},
    ) if g["items"]]


def not_checked(p):
    """What nothing checked, as labelled groups of short rows."""
    claims = {c["id"]: c for c in p["claims"]}
    opinion = [{"id": c["id"], "text": c["summary"]} for c in p["claims"] if c["status"] == "opinion"]
    criteria = []
    for k in p["requirement"]["criteria"]:
        serving = [c for c in claims.values() if k["id"] in c["criteria"]]
        if not any(c["status"] == "checked" for c in serving):
            ids = ", ".join(c["id"] for c in serving)
            detail = (f"claim {ids} has" if len(serving) == 1 else f"claims {ids} have") + " no failing test" if serving else "no claim addresses it"
            criteria.append({"id": k["id"], "text": k["text"], "detail": detail})
    return [g for g in (
        {"label": "Claims without a failing test", "note": "The writer model's reading of the diff; read their code.",
         "items": opinion},
        {"label": "Requirement criteria without a checked claim", "items": criteria},
        {"label": "Environment", "items": [{"text": e} for e in p["environment"]]},
        {"label": "Outside the review", "items": [{"text": "Documentation accuracy (the writer model reads it)"},
                                                  {"text": "Performance and allocations"}]},
    ) if g["items"]]
