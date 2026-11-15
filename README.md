# Trust the process

AI code review in which a named engineer stays accountable for every merge. The reviewer restates an agent-written change as claims tied to requirement criteria. A claim counts as checked only when reverting its own code makes a test fail. A second model family attacks the claims with probe tests, and decisions reserved for humans go to the owner as questions. Readable rules decide how deeply each part is read, and the owner signs a record of what was checked, what was not and the risk they accept. `CONCEPT.md` is the concept card with the measured results.

Built for Tieto's "Earned Trust in AI Code" challenge at Junction 2026, on agent-written branches of [junction26-messagepack-csharp](https://github.com/te-industry-tech-office/junction26-messagepack-csharp).

## Layout

| Path | Contents |
|---|---|
| `app/review.py` | Reviews one change end to end: requirement intake, diff partition, surface rules, claims, per-claim reverts, adversary probes, refused decisions and routing. Writes `data/packets/<name>.json` |
| `app/web.py` | Web UI: the review packet as a walkthrough, and the owner's sign-off |
| `app/bench.py` | Planted-defect benchmark: folds one defect at a time into an agent commit as a `bench/<name>` branch, reviews it and scores the result into `data/bench.json` |
| `app/rules.py`, `app/surface.py` | The routing rules and the API-surface checks |
| `checks/` | Build, test and revert scripts that run on a Linux build host with the .NET SDK; `setup_instance.sh` prepares a fresh Ubuntu 24.04 host |
| `data/` | The four changes (`prs.json`), their requirement criteria, the review packets, the benchmark results and the per-area track record (`areas.json`) |

## Running it

The web UI shows the packets in `data/packets/` and needs nothing else:

```sh
cd app
uv run uvicorn web:app --port 8310
```

Running new reviews needs:

- the fork cloned at `~/code/cloned/junction26-messagepack-csharp` (`app/partition.py`, `REPO`)
- a build host prepared with `checks/setup_instance.sh` and reachable over SSH (`app/remote.py`, `HOST`)
- an OpenAI-compatible inference key in `~/.config/junction/verda-inference.env`. The writer model is Kimi K3.1 Pro and the adversary DeepSeek 4.1 Flash, both on Verda's inference API (`app/llm.py`)

```sh
cd app
uv run review.py 2283          # names and refs are in data/prs.json; --fresh ignores cached results
uv run bench.py plant          # then: bench.py review, bench.py score
```
