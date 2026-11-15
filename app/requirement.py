"""Requirement intake: the upstream issue body and thread, split into numbered acceptance criteria by the writer model.
Maintainer comments outrank the original request. Cached in data/requirements/<issue>.json."""
import json
import re
import sys
import urllib.request
from pathlib import Path

import llm

DATA = Path(__file__).parent.parent / "data"
UPSTREAM = "https://api.github.com/repos/MessagePack-CSharp/MessagePack-CSharp/issues"

SYSTEM = """You turn a GitHub issue thread into the requirement an implementation is reviewed against.
Write numbered acceptance criteria that a reviewer can check one by one. Each criterion is one testable statement.
Comments by maintainers (author_association OWNER, MEMBER or COLLABORATOR) state design decisions and outrank the original
request; a criterion that comes from a comment names its author. Keep only what the thread asks for or decides; do not
invent criteria. List separately the points the thread leaves open or ambiguous, as questions.
Reply with JSON: {"summary": str, "criteria": [{"text": str, "source": str}], "open_questions": [str]}
"source" is "issue body" or "comment by <login> (<association>)"."""


def fetch(issue):
    req = lambda url: json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "earned-trust"})))
    body = req(f"{UPSTREAM}/{issue}")
    comments = req(f"{UPSTREAM}/{issue}/comments?per_page=100")
    return {"number": issue, "title": body["title"], "url": body["html_url"], "author": body["user"]["login"],
            "body": body["body"] or "",
            "comments": [{"author": c["user"]["login"], "association": c["author_association"], "body": c["body"]}
                         for c in comments]}


def requirement(issue):
    path = DATA / "requirements" / f"{issue}.json"
    if path.exists():
        return json.loads(path.read_text())
    thread = fetch(issue)
    usage = llm.Usage()
    text = f"# #{issue} {thread['title']}\nby {thread['author']}\n\n{thread['body']}\n\n" + "\n\n".join(
        f"## Comment by {c['author']} ({c['association']})\n{c['body']}" for c in thread["comments"])
    r = llm.ask_json(llm.WRITER, SYSTEM, text, usage)
    req = {"issue": issue, "title": thread["title"], "url": thread["url"], "summary": r["summary"],
           "criteria": [{"id": f"REQ-{issue}.{i}", "text": re.sub(r"^\d+\.\s*", "", c["text"]), "source": c["source"]}
                        for i, c in enumerate(r["criteria"], 1)],
           "open_questions": r.get("open_questions", []), "thread": thread, "usd": usage.usd}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(req, indent=1))
    return req


if __name__ == "__main__":
    for n in sys.argv[1:]:
        r = requirement(int(n))
        print(f"#{n} {r['title']} (${r['usd']:.4f})")
        for c in r["criteria"]:
            print(f"  {c['id']} [{c['source']}] {c['text']}")
        for q in r["open_questions"]:
            print(f"  ? {q}")
