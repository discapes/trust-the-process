"""A model from a different family tries to break the claims by writing probes: test files dropped into a test project,
or standalone projects. A finding is posted only when its probe reproduces it; probes that do not reproduce are kept as
attacks the change survived."""
import re

import checks
import claims as claims_mod
import llm

SYSTEM = """You are the adversary in an AI code review of MessagePack-CSharp (C#, xUnit). Another model restated an
agent-written change as claims. Your job is to show where the change is wrong: write probes that fail if it is.

Probe kinds:
- "test": one C# test file added to a test project of the repo at the branch head. Assert the behaviour the requirement
  or the claim demands; the probe confirms your hypothesis when the test FAILS at the head. Test projects:
  MessagePack.SourceGenerator.Tests (analyzer and generator tests; copy the harness the change's own tests use, e.g.
  `using VerifyCS = CSharpCodeFixVerifier<MessagePack.SourceGenerator.Analyzers.MsgPack00xMessagePackAnalyzer,
  MessagePack.Analyzers.CodeFixes.MessagePackCodeFixProvider>;` with `{|MsgPack005:Member|}` markup, or the verifiers in
  the change's tests), MessagePack.SourceGenerator.ExecutionTests (round trips through generated formatters),
  MessagePack.Tests (runtime serializer). Use a unique class name starting with "Probe". Keep usings explicit.
- "project": a standalone SDK-style project ({"probe.csproj": ..., "Probe.cs": ...}) built with `dotnet build`, for
  premises about compilers, target frameworks or packages (e.g. whether an API exists on netstandard2.0; reference
  Microsoft.NETFramework.ReferenceAssemblies 1.0.3 for net472). "expect" is the build result that confirms your hypothesis.

A test probe in MessagePack.SourceGenerator.Tests that compiles (analyzer diagnostics checked with markup):
```
using MessagePack.SourceGenerator.Analyzers;
using Microsoft.CodeAnalysis.Testing;
using VerifyCS = CSharpCodeFixVerifier<MessagePack.SourceGenerator.Analyzers.MsgPack00xMessagePackAnalyzer, MessagePack.Analyzers.CodeFixes.MessagePackCodeFixProvider>;

public class ProbeNullKeyTests
{
    [Fact]
    public async Task NullStringKeyIsReported()
    {
        string input = @"
using MessagePack;

[MessagePackObject]
public class Foo
{
    [Key(null)]
    public string {|MsgPack005:Member|} { get; set; }
}
";
        await new VerifyCS.Test { TestCode = input, MarkupOptions = MarkupOptions.UseFirstDescriptor }.RunAsync();
    }
}
```
Several diagnostics share an ID, so set MarkupOptions.UseFirstDescriptor when you use markup.

Write at most 3 probes, each aimed at a different, concrete hypothesis; prefer the suspicions listed and premises stated
in the change's own comments and tests. Do not probe what the requirement does not ask for.

Reply with JSON:
{"probes": [{"title": str, "hypothesis": str, "claims": [str], "criteria": [str], "kind": "test" | "project",
  "project": str, "file_name": str, "code": str,
  "files": {str: str}, "expect": "build-succeeds" | "build-fails",
  "means": str}]}
"project", "file_name" and "code" are for test probes; "files" and "expect" for project probes. "means" says what a
confirming result shows about the change."""

REPAIR = """Your probe did not compile. Fix it so it compiles and still tests the same hypothesis. Reply with the same JSON
object for this one probe."""

VERIFY = """You verify a finding before it is posted to a human owner. An adversary wrote a probe test to show that an
agent-written change is wrong, and the probe failed at the branch head. Decide from the probe code and the outputs alone
whether the failing assertion itself shows the hypothesized defect in the change.
- "demonstrates": the assertion that failed checks behaviour the requirement or the claim demands, and it failed because
  the changed code behaves wrongly.
- "probe broken": the failure comes from the probe (misused test harness, wrong type or member names, an expectation the
  requirement does not ask for, an assertion unrelated to the hypothesis), even if other parts of the probe pass.
- "inconclusive": the output does not show which.
The base commit's result is given for contrast. Reply with JSON: {"verdict": str, "reason": str}"""

FIX = """A reviewer from another model family judged your probe broken for the reason below. Fix the probe so it tests the
same hypothesis correctly, or give up if the hypothesis does not hold. Reply with JSON: {"probe": <the fixed probe object>}
or {"give_up": str}."""


def one(r):
    """The single probe object in a reply, however the model wrapped it."""
    v = r.get("probes", r.get("probe", r))
    return v[0] if isinstance(v, list) else v


def probe_fields(p):
    return str({k: p[k] for k in p if k in ("title", "hypothesis", "kind", "project", "file_name", "code", "files", "expect")})


def attack(req, part, cl, ref, name, usage):
    user = (claims_mod.render_requirement(req)
            + "\n\n# Claims\n" + "\n".join(f"- {c['id']}: {c['statement']} (hunks {', '.join(c['hunks'])})" for c in cl["claims"])
            + "\n\n# Suspicions raised by the writer\n" + "\n".join(f"- {s['hypothesis']}" for s in cl.get("suspicions", []))
            + "\n\n# Hand-written hunks\n" + claims_mod.render_hunks(part["hunks"]))
    probes = llm.ask_json(llm.ADVERSARY, SYSTEM, user, usage).get("probes", [])[:3]
    for i, p in enumerate(probes, 1):
        p["id"], p["rounds"] = f"P{i}", []
        for _ in range(3):  # first run plus up to two repairs
            run(p, ref, f"{name}-probe-{p['id']}")
            if p["result"] == "probe does not compile":
                ask = REPAIR + "\n\n# Errors\n" + p["head"]["log"]
            elif p["result"] == "failed" and p["kind"] == "test":
                base = p["base"]["log"] if p["base"]["compiled"] else "does not compile at the base"
                v = llm.ask_json(llm.WRITER, VERIFY, claims_mod.render_requirement(req) + "\n\n# Hypothesis\n" + p["hypothesis"]
                                 + "\n\n# Probe\n" + p["code"] + "\n\n# Output at the head\n" + p["head"]["log"]
                                 + "\n\n# Output at the base\n" + base, usage)
                p["rounds"].append({"verdict": v.get("verdict"), "reason": v.get("reason"), "by": llm.WRITER})
                if v.get("verdict") == "demonstrates":
                    p["result"], p["verdict"] = "reproduced", v.get("reason")
                    break
                p["result"] = "probe broken" if v.get("verdict") == "probe broken" else "inconclusive"
                fixed = llm.ask_json(llm.ADVERSARY, SYSTEM, user + "\n\n# Your probe\n" + probe_fields(p) + "\n\n# Reason\n"
                                     + str(v.get("reason")) + "\n\n" + FIX, usage)
                if "give_up" in fixed or not isinstance(fixed.get("probe"), dict):
                    p["rounds"].append({"verdict": "adversary gave up", "reason": fixed.get("give_up"), "by": llm.ADVERSARY})
                    break
                p.update({k: one(fixed)[k] for k in ("code", "file_name", "project") if k in one(fixed)})
                continue
            else:
                break
            fixed = llm.ask_json(llm.ADVERSARY, SYSTEM, user + "\n\n# Your probe\n" + probe_fields(p) + "\n\n" + ask, usage)
            fixed = one(fixed)
            p["rounds"].append({"verdict": "does not compile", "reason": p["head"]["log"][:300]})
            p.update({k: fixed[k] for k in ("code", "files", "file_name", "project", "expect") if k in fixed})
    return probes


def run(p, ref, job):
    if p.get("kind") == "project":
        r = checks.project_job(job, p["files"]).result()
        p["head"] = r
        confirmed = r["built"] == (p.get("expect") == "build-succeeds")
        p["result"] = "reproduced" if confirmed else "not reproduced"
        if confirmed:  # the build result is unambiguous, so no model judges it
            p["verdict"] = f"The probe project {'built' if r['built'] else 'failed to build'}, as the hypothesis predicts."
        return
    p["file_name"] = re.sub(r"[^\w.]", "", p.get("file_name") or "ProbeTests.cs")
    p["project"] = p["project"].strip("/").removeprefix("tests/")
    add = {p["file_name"]: (p["project"], p["code"])}
    cls = re.findall(r"class\s+(Probe\w*)", p["code"])[:1] or re.findall(r"class\s+(\w+)", p["code"])[:1]
    head = checks.test_job(job, ref, cls, [p["project"]], add=add)
    base = checks.test_job(f"{job}-base", "32258fdb", cls, [p["project"]], add=add)
    p["head"], p["base"] = head.result(), base.result()
    outs = p["head"]["outcomes"].values()
    if not p["head"]["compiled"]:
        p["result"] = "probe does not compile"
    elif any(o == "Failed" for o in outs):
        p["result"] = "failed"  # a finding only once the failure is judged to demonstrate the hypothesis
    else:
        p["result"] = "not reproduced"
