"""The writer model restates a change as claims: what the code does, which requirement criteria it serves, which hunks
implement it and which new tests should fail without it. It derives them from the diff, not from the agent's commit message."""
import json
from pathlib import Path

import llm

SYSTEM = """You review a code change written by an AI coding agent. You never approve it: you restate it as claims a
human owner can check, and you say which decisions you refuse to make.

Claims:
- A claim states one specific, falsifiable thing the changed code does, in plain words ("TypeCollector reports MsgPack004
  at Location.None instead of indexing DeclaringSyntaxReferences[0] when the member comes from metadata"). Describe what
  the code does, derived from the diff. Do not repeat the commit message or the agent's comments as fact.
- Every source and build hunk must belong to at least one claim. Test and documentation hunks may belong to claims too
  ("README documents X"). If you cannot explain a hunk, leave it out; it will be flagged as unexplained.
- "criteria" lists the requirement criteria the claim serves. A claim that serves none (scope beyond the requirement)
  has an empty list.
- "tests" lists new test methods, by their exact names from the list given, that should fail if the claim's hunks were
  reverted. Do not list tests that only touch the claim's area loosely.

Refusals: you never decide these, whatever your confidence. Raise each one that applies as a specific question:
public API shape; new diagnostic IDs, titles and severities; intentional behaviour changes, including diagnostics that
are now reported differently, moved or dropped; regressions and which branch a fix belongs on; deserialization security;
new dependencies and licences; interpretations of an ambiguous requirement; work the change does beyond the requirement.

Suspicions: concrete ways the change could be wrong that a test could show (an input the code mishandles, a criterion it
misses, a premise in its comments or tests that may be false). Each is a hypothesis for an adversary to probe.

Reply with JSON:
{"claims": [{"statement": str, "criteria": [str], "hunks": [str], "tests": [str]}],
 "questions": [{"question": str, "why": str, "hunks": [str]}],
 "suspicions": [{"hypothesis": str, "hunks": [str]}]}"""


def render_hunks(hunks):
    return "\n\n".join(f"### {h['id']} {h['kind']} {h['path']} @@ -{h['old_start']} +{h['new_start']} @@ {h['context']}\n"
                       + "\n".join(h["lines"]) for h in hunks)


def render_requirement(req):
    return (f"# Requirement: #{req['issue']} {req['title']}\n{req['summary']}\n\n"
            + "\n".join(f"- {c['id']}: {c['text']} ({c['source']})" for c in req["criteria"]))


def claims(req, part, new_tests, usage):
    clusters = "\n".join(f"- {c['id']}: {len(c['files'])} generated files share this edit: " + " | ".join(c["edit"])[:600]
                         for c in part["clusters"])
    user = (render_requirement(req) + "\n\n# New test methods\n" + "\n".join(f"- {t}" for t in new_tests)
            + ("\n\n# Generated files (checked separately by cluster)\n" + clusters if clusters else "")
            + "\n\n# Hand-written hunks\n" + render_hunks(part["hunks"]))
    r = llm.ask_json(llm.WRITER, SYSTEM, user, usage, effort="high")
    known_hunks, known_tests = {h["id"] for h in part["hunks"]}, set(new_tests)
    for i, c in enumerate(r["claims"], 1):
        c["id"] = f"C{i}"
        c["hunks"] = [h for h in c.get("hunks", []) if h in known_hunks]  # drop IDs the model made up
        c["tests"] = [t for t in c.get("tests", []) if t in known_tests]
        c["criteria"] = [x for x in c.get("criteria", []) if x in {k["id"] for k in req["criteria"]}]
    return r


SUMMARY = """Give each numbered item from a code review a short summary a reviewer can scan: at most 12 words, plain
words, no trailing period, code names kept exact. A claim says what the code does. A requirement criterion says what must
hold. A decision starts with the action the owner takes (Approve, Decide, Confirm) and names the specific thing, using its
context when the question is generic.
Reply with JSON: {"summaries": {"<number>": str}}"""
SUMMARIES = Path(__file__).parent.parent / "data" / "summaries.json"


def summaries(texts, usage):
    """Short summary of each claim statement or decision question, cached by the exact text."""
    done = json.loads(SUMMARIES.read_text()) if SUMMARIES.exists() else {}
    todo = list(dict.fromkeys(t for t in texts if t not in done))
    if todo:
        r = llm.ask_json(llm.WRITER, SUMMARY, "\n".join(f"{i}. {t}" for i, t in enumerate(todo)), usage, effort="low")
        done |= {t: r["summaries"][str(i)] for i, t in enumerate(todo) if str(i) in r["summaries"]}
        SUMMARIES.write_text(json.dumps(done, indent=1))
    return {t: done.get(t, t) for t in texts}
