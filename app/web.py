"""Review walkthrough and sign-off UI: one page per agent-written change, the owner's signed record, the track record of
each code area, the planted-defect benchmark and the concept card."""
import json
import re
import time
from pathlib import Path

import markdown
from markupsafe import Markup, escape
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import rules

HERE = Path(__file__).parent
DATA = rules.DATA
app = FastAPI()
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.filters["pct"] = lambda x: f"{x:.0%}"
templates.env.filters["short"] = lambda s: s[:7]
templates.env.filters["num"] = lambda n: f"{n:,}"
def dedent(lines):
    """Diff lines without the indentation they all share, keeping each line's +/-/space marker."""
    body = [l[1:].rstrip("\r").expandtabs(4) for l in lines]
    cut = min((len(b) - len(b.lstrip(" ")) for b in body if b.strip()), default=0)
    return [l[0] + b[cut:] for l, b in zip(lines, body)]


templates.env.filters["dedent"] = dedent
templates.env.filters["mdblock"] = lambda s: Markup(markdown.markdown(s, extensions=["tables", "fenced_code"]))
templates.env.filters["md"] = lambda s: Markup(re.sub(r"`([^`]+)`", r"<code>\1</code>", str(escape(s or ""))))


@app.middleware("http")
async def no_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response


def packets():
    order = list(json.loads((DATA / "prs.json").read_text()))
    found = {p.stem: json.loads(p.read_text()) for p in (DATA / "packets").glob("*.json")}
    return [found[n] for n in order if n in found]


def packet(name):
    return json.loads((DATA / "packets" / f"{name}.json").read_text())


def signoff(name):
    path = DATA / "signoffs" / f"{name}.json"
    return json.loads(path.read_text()) if path.exists() else None


def summary(p):
    status = [c["status"] for c in p["claims"]]
    return {"checked": status.count("checked"), "opinion": status.count("opinion"), "contradicted": status.count("contradicted"),
            "findings": sum(x["result"] == "reproduced" for x in p["probes"]), "refusals": len(p["refusals"])}


def record(p, form):
    """The signed record: what was checked and by whom or what, what was not, and the residual risk the owner accepts."""
    reads = [u for u in p["routing"]["units"] if u["depth"] != "light"]
    owner = {"label": f"Read by {form['owner']}", "items": [
        {"text": f"{p['routing']['read_lines']:,} of {p['routing']['total_lines']:,} changed lines"},
        *({"text": u["representative"] if u["kind"] == "generated" else u["unit"], "detail": u["depth"]} for u in reads)]}
    answers = [{"id": r["id"], "summary": r.get("summary", r["question"]), "question": r["question"], "why": r["why"],
                "answer": form.get(f"answer_{r['id']}", ""),
                "note": form.get(f"note_{r['id']}", "")} for r in p["refusals"]]
    findings = [{"id": x["id"], "title": x["title"], "hypothesis": x["hypothesis"], "answer": form.get(f"answer_{x['id']}", ""), "note": form.get(f"note_{x['id']}", "")}
                for x in p["probes"] if x["result"] == "reproduced"]
    return {"name": p["name"], "sha": p["commit"]["sha"], "requirement": f"#{p['issue']} {p['requirement']['title']}",
            "owner": form["owner"], "decision": form["decision"], "signed_at": time.strftime("%Y-%m-%d %H:%M"),
            "checked": rules.checked(p) + [owner], "not_checked": rules.not_checked(p), "answers": answers,
            "findings": findings, "residual_risk": form.get("residual_risk", ""), "summary": summary(p)}


def group_markdown(title, groups):
    out = [f"**{title}**"]
    for g in groups:
        out.append(f"- {g['label']}")
        out += [f"  - {(i['id'] + ' ') if i.get('id') else ''}{i['text']}" + (f" ({i['detail']})" if i.get("detail") else "") for i in g["items"]]
    return out + [""]


def record_markdown(r):
    out = [f"**{r['decision']}** by {r['owner']}, {r['signed_at']}, for `{r['sha'][:7]}` ({r['requirement']})", "",
           *group_markdown("Checked", r["checked"]), *group_markdown("Not checked", r["not_checked"])]
    if r["answers"]:
        out += ["**Decisions the AI refused to make**", *[f"- {a['id']} {a['question']} **{a['answer']}**" + (f": {a['note']}" if a["note"] else "")
                                                         for a in r["answers"]], ""]
    if r["findings"]:
        out += ["**Findings**", *[f"- {f['id']} {f['title']}: **{f['answer']}**" + (f": {f['note']}" if f["note"] else "")
                                  for f in r["findings"]], ""]
    out += ["**Residual risk accepted**", r["residual_risk"] or "None stated."]
    return "\n".join(out)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    rows = [(p, summary(p), signoff(p["name"])) for p in packets() if not p.get("defect")]
    return templates.TemplateResponse(request, "index.html", {"rows": rows, "nav": "changes"})


@app.get("/pr/{name}", response_class=HTMLResponse)
def walkthrough(request: Request, name: str):
    p = packet(name)
    hunks = {h["id"]: h for h in p["hunks"]}
    # Documentation hunks are shown in their claims as the text the agent added, rendered as Markdown.
    doc_text = {h["id"]: "\n".join(l[1:].rstrip("\r") for l in h["lines"] if l[0] == "+") for h in p["hunks"] if h["kind"] == "doc"}
    claims_by_hunk = {}
    for c in p["claims"]:
        for h in c["hunks"]:
            claims_by_hunk.setdefault(h, []).append(c)
    files = {}
    for h in p["hunks"]:
        files.setdefault(h["path"], []).append(h)
    units = {u["unit"]: u for u in p["routing"]["units"]}
    read_of = {h: u for u in p["routing"]["units"] for h in u.get("read_hunks", [])}  # hunks the owner must read
    # Where each routing reason comes from: a rule links to the decision it raised, else to the first hunk it fired on.
    rule_target = {s["rule"]: s["hunks"][0] for s in p["signals"] if s["hunks"]}
    rule_target |= {r["source"].removeprefix("rule "): r["id"] for r in p["refusals"] if r["source"].startswith("rule ")}

    def refs(text):
        html = re.sub(r"\b([CRHGP]\d+)\b", r'<a class="ref" href="#\1">\1</a>', str(escape(text)))
        html = re.sub(r"\brule ([a-z-]+)", lambda m: f'rule <a href="#{rule_target[m[1]]}">{m[1]}</a>' if m[1] in rule_target else m[0], html)
        return Markup(re.sub(r"(area .+? is on probation)", r'<a href="/track">\1</a>', html))
    return templates.TemplateResponse(request, "pr.html", {
        "p": p, "s": summary(p), "hunks": hunks, "doc_text": doc_text, "refs": refs, "read_of": read_of,
        "serving_of": {k["id"]: [c for c in p["claims"] if k["id"] in c["criteria"]] for k in p["requirement"]["criteria"]}, "files": files, "units": units, "claims_by_hunk": claims_by_hunk,
        "signed": signoff(name), "nav": "changes",
        # The same groups the signed record lists, keyed by label so the page can place each one where it is used.
        "checked": {g["label"]: g for g in rules.checked(p)}, "not_checked": {g["label"]: g for g in rules.not_checked(p)}})


@app.post("/pr/{name}/signoff", response_class=HTMLResponse)
async def sign(request: Request, name: str):
    form = dict(await request.form())
    r = record(packet(name), form)
    path = DATA / "signoffs" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(r, indent=1))
    return templates.TemplateResponse(request, "record.html", {"r": r, "md": record_markdown(r), "p": packet(name)})


@app.post("/pr/{name}/unsign")
def unsign(name: str):
    (DATA / "signoffs" / f"{name}.json").unlink(missing_ok=True)
    return RedirectResponse(f"/pr/{name}#signoff", status_code=303)


@app.get("/pr/{name}/record.md", response_class=PlainTextResponse)
def record_md(name: str):
    return record_markdown(signoff(name))


@app.get("/track", response_class=HTMLResponse)
def track(request: Request):
    areas = rules.areas()
    for a in areas:
        a["tier"] = rules.tier(a)
    return templates.TemplateResponse(request, "track.html", {"areas": areas, "names": [p["name"] for p in packets()],
                                                              "spot": rules.SPOT_CHECK, "nav": "track"})


@app.post("/track")
def add_event(area: str = Form(), kind: str = Form(), detail: str = Form(""), change: str = Form("")):
    areas = rules.areas()
    next(a for a in areas if a["name"] == area)["history"].append(
        {"date": time.strftime("%Y-%m-%d"), "kind": kind, "detail": detail, "change": change})
    (DATA / "areas.json").write_text(json.dumps(areas, indent=1))
    return RedirectResponse("/track", status_code=303)


@app.get("/bench", response_class=HTMLResponse)
def bench(request: Request):
    path = DATA / "bench.json"
    return templates.TemplateResponse(request, "bench.html", {"b": json.loads(path.read_text()) if path.exists() else None, "nav": "bench"})


@app.get("/concept", response_class=HTMLResponse)
def concept(request: Request):
    html = markdown.markdown((HERE.parent / "CONCEPT.md").read_text(), extensions=["tables"])
    return templates.TemplateResponse(request, "concept.html", {"html": html, "nav": "concept"})
