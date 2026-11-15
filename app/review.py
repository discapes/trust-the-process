"""Review one agent-written change end to end and write its packet to data/packets/<name>.json.
Usage: review.py <name> [--fresh]   names and refs are in data/prs.json. Model and instance results are cached in
data/cache/<name>/ so later steps can be rerun cheaply; --fresh redoes everything."""
import json
import shutil
import sys
import time

import adversary
import checks
import claims
import llm
import partition
import remote
import requirement
import rules
import surface

DATA = rules.DATA
ENVIRONMENT = [
    "Linux only: net472 targets and Windows-only tests did not run",
    ".NET SDK 9.0.321 instead of the pinned 8.0.402, which cannot load the repo's Roslyn 4.12 generator",
]


def cached(name, step, fn):
    """The step's cached result; its first run's duration is kept next to it, so a rerun reports the real review time."""
    path = DATA / "cache" / name / f"{step}.json"
    if not path.exists():
        started = time.time()
        value = fn()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=1))
        path.with_suffix(".seconds").write_text(str(round(time.time() - started)))
    return json.loads(path.read_text())


def on_instance(ref, fn):
    """A step that runs on the build instance: copy the check scripts and the ref there first, once per review."""
    def run():
        remote.sync_scripts()
        if not ref.startswith("origin/"):
            remote.push(ref)
        return fn()
    return run


def claim_reverts(name, ref, part, cl, fb):
    """Revert each claim's own source hunks (not shared with another claim) and run the tests that exercise the change."""
    exercising = [t for t, v in fb["new_tests"].items() if v == "exercises the change"] + fb["existing_tests_exercising_change"]
    kinds = {h["id"]: h for h in part["hunks"]}
    shared = {h for c in cl["claims"] for h in c["hunks"] if sum(h in d["hunks"] for d in cl["claims"]) > 1}
    jobs = {}
    for c in cl["claims"]:
        own = [kinds[h] for h in c["hunks"] if h not in shared and kinds[h]["kind"] in ("source", "build")]
        for tt in sorted({h["path"] for h in own if h["path"].endswith(".tt")}):  # the compiled code is the T4 output next to it
            own += [h | {"id": f"{tt[:-3].rsplit('/', 1)[-1]}.cs", "path": tt[:-3] + ".cs"} for h in partition.hunks_of(ref, tt[:-3] + ".cs")]
        if own and exercising:
            jobs[c["id"]] = (own, checks.test_job(f"{name}-claim-{c['id']}", ref, exercising, checks.projects(ref, exercising), revert=own))
    out = {}
    for cid, (own, job) in jobs.items():
        r = job.result()
        out[cid] = {"hunks": list(dict.fromkeys(h["id"] for h in own)), "compiled": r["compiled"], "log": r["log"],
                    "failing_tests": sorted(t for t, o in r["outcomes"].items() if o == "Failed"),
                    "passing_tests": sorted(t for t, o in r["outcomes"].items() if o == "Passed")}
    return out


def review(name, fresh=False):
    pr = json.loads((DATA / "prs.json").read_text())[name]
    ref = pr["ref"]
    if fresh:
        shutil.rmtree(DATA / "cache" / name, ignore_errors=True)
    usage = llm.Usage()
    req = requirement.requirement(pr["issue"])
    part = partition.partition(ref)
    signals = surface.signals(part["hunks"])
    fb = cached(name, "failbefore", on_instance(ref, lambda: checks.suite(name, ref)))
    returned = None if fb["suite_passed"] else (
        "The change fails its own build or tests at the head, so it goes back to the agent before any human review. Failing: "
        + (", ".join(fb.get("failing_at_head") or []) or "the build"))

    def write_claims():
        r = claims.claims(req, part, list(fb["new_tests"]) + fb["existing_tests_exercising_change"], usage)
        return r | {"usage": usage.calls}
    cl = {"claims": []} if returned else cached(name, "claims", write_claims)
    reverts = {} if returned else cached(name, "reverts", on_instance(ref, lambda: claim_reverts(name, ref, part, cl, fb)))
    for c in cl["claims"]:
        c["revert"] = reverts.get(c["id"])
        c["status"] = rules.claim_status(c, [])

    def attack():
        before = len(usage.calls)
        return {"probes": adversary.attack(req, part, cl, ref, name, usage), "usage": usage.calls[before:]}
    adv = {"probes": []} if returned else cached(name, "probes", on_instance(ref, attack))
    probes = adv["probes"]
    for c in cl["claims"]:
        c["status"] = rules.claim_status(c, probes)

    covered = {h for c in cl["claims"] for h in c["hunks"]}
    unexplained = [] if returned else [h["id"] for h in part["hunks"] if h["id"] not in covered and h["kind"] in ("source", "build")]
    sha, author, date, message = partition.git("show", "-s", "--format=%H%n%an%n%ad%n%B", "--date=iso", ref).split("\n", 3)
    calls = cl.get("usage", []) + adv.get("usage", [])
    refusals = rules.refusals(signals, cl.get("questions", []), fb["new_tests"])
    asked = {r["id"]: f"Decision: {r['question']} Context: {r['why']}" for r in refusals}
    short = claims.summaries([f"Claim: {c['statement']}" for c in cl["claims"]] + list(asked.values())
                             + [f"Requirement criterion: {k['text']}" for k in req["criteria"]]
                             + [f"Requirement: {req['summary']}"], llm.Usage())
    req["short"] = short[f"Requirement: {req['summary']}"]
    for k in req["criteria"]:
        k["summary"] = short[f"Requirement criterion: {k['text']}"]
    for c in cl["claims"]:
        c["summary"] = short[f"Claim: {c['statement']}"]
    for r in refusals:
        r["summary"] = short[asked[r["id"]]]
    packet = {
        "name": name, "ref": ref, "issue": pr["issue"], "owner": pr.get("owner"), "note": pr.get("note"), "defect": pr.get("defect"),
        "commit": {"sha": sha, "author": author, "date": date, "message": message.strip()},
        "requirement": {k: v for k, v in req.items() if k != "thread"},
        "environment": ENVIRONMENT,
        "suite": {"passed": fb["suite_passed"], "builds": fb["builds"], "totals": fb["totals"], "regressions": fb["regressions"]},
        "failbefore": {"new_tests": fb["new_tests"], "existing_tests_exercising_change": fb["existing_tests_exercising_change"]},
        "hunks": part["hunks"], "clusters": part["clusters"],
        "claims": cl["claims"], "facts": surface.facts(part["hunks"], part["clusters"]), "unexplained": unexplained,
        "suspicions": cl.get("suspicions", []), "signals": signals, "probes": probes,
        "refusals": refusals,
        "routing": rules.routing(part["hunks"], part["clusters"], cl["claims"], signals, probes, unexplained, refusals, sha, returned),
        "returned": returned,
        "cost": {"usd": sum(c["usd"] for c in calls) + req.get("usd", 0), "calls": calls,
                 "tokens": sum(c["prompt"] + c["completion"] for c in calls)},
        "reviewed_at": time.strftime("%Y-%m-%d %H:%M"),
        "seconds": sum(int(f.read_text()) for f in (DATA / "cache" / name).glob("*.seconds")),
    }
    path = DATA / "packets" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(packet, indent=1))
    return packet


if __name__ == "__main__":
    p = review(sys.argv[1], "--fresh" in sys.argv)
    r = p["routing"]
    print(f"{p['name']}: {len(p['claims'])} claims ({', '.join(c['id'] + ' ' + c['status'] for c in p['claims'])}), "
          f"{len(p['unexplained'])} unexplained, {len(p['refusals'])} refusals, "
          f"probes {[x['result'] for x in p['probes']]}, human reads {r['read_lines']}/{r['total_lines']} lines "
          f"({r['share']:.0%}), ${p['cost']['usd']:.3f}, {p['seconds']} s")
