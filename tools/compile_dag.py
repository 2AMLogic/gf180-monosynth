#!/usr/bin/env python3
"""Compile the capability DAG from evidence, and render it into README.md.

A node is not green because someone wrote that it is. Every node in
docs/dag.json names the evidence that would make it green, and this script
checks that evidence exists and is not older than the files it covers.

This exists because docs/capability-dag.md twice carried findings that had
already been fixed -- the modal_dp exc hazard, and red on four repaired drum
circuits. Both were hand-maintained claims that outlived their evidence.
See docs/failure-modes.md, mechanism 4.

Status is derived, never asserted:

  STAMPED   an annotated git tag exists, and its commit is an ancestor of HEAD
  GREEN     the evidence exists (a suite collects, a verifier is present,
            a report file is committed) but no tag has been cut
  STALE     the evidence exists but predates a file it covers
  BLOCKED   the node declares what it is waiting for
  TODO      no evidence yet; an issue number if one is filed

Run with --check to fail when anything is STALE, which is the state that
matters: a green claim whose evidence has gone out from under it.
"""
from __future__ import annotations
import argparse, json, os, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DAG = ROOT / "docs" / "dag.json"
README = ROOT / "README.md"
BEGIN, END = "<!-- DAG:BEGIN -->", "<!-- DAG:END -->"

GROUPS = {"foundation": "Foundation", "minimoog": "Minimoog voice",
          "drums": "TR-808 drums", "integration": "Integration", "silicon": "Silicon"}

# Only subsystems that MAKE A SOUND can be compared to an external reference.
# A control link or a routed die has no Minimoog to be measured against, so
# demanding fidelity evidence there would be noise that trains people to ignore
# the warning -- which is how a real UNVALIDATED goes unnoticed.
NEEDS_FIDELITY = {"minimoog", "drums"}


def git(*a: str) -> str:
    try:
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True,
                              text=True, timeout=30).stdout.strip()
    except Exception:
        return ""


def tag_is_ancestor(tag: str) -> bool:
    """A tag on a commit no longer in this history is not evidence."""
    if not tag or tag not in git("tag", "-l").split():
        return False
    sha = git("rev-list", "-n1", tag)
    if not sha:
        return False
    r = subprocess.run(["git", "merge-base", "--is-ancestor", sha, "HEAD"],
                       cwd=ROOT, capture_output=True)
    return r.returncode == 0


def mtime_commit(path: str) -> int:
    """Commit time of a path's last change, 0 if untracked or absent."""
    out = git("log", "-1", "--format=%ct", "--", path)
    return int(out) if out.isdigit() else 0


def classify(nid: str, n: dict) -> tuple[str, str]:
    """Return (status, note). Derived from evidence; never taken on trust."""
    if n.get("blocked"):
        return "BLOCKED", n["blocked"]

    # What would make this node true?
    sources = [n[k] for k in ("verifier", "suite", "tool", "evidence_file") if k in n]
    if not sources:
        iss = n.get("issue")
        return "TODO", (f"issue #{iss}" if iss else "no evidence declared")

    missing = [s for s in sources if not (ROOT / s).exists()]
    if missing:
        return "TODO", "missing: " + ", ".join(missing)

    # STALE: the evidence predates something it is supposed to cover. For a
    # committed report this is real; for a suite it is a weaker signal, so we
    # only apply it to evidence_file, where the file IS the result.
    if "evidence_file" in n:
        ev = mtime_commit(n["evidence_file"])
        for dep_path in n.get("covers", []):
            if mtime_commit(dep_path) > ev:
                return "STALE", f"{dep_path} changed after the evidence was recorded"

    if tag_is_ancestor(n.get("tag", "")):
        return "STAMPED", n["tag"]
    return "GREEN", ", ".join(sources)


def mermaid(nodes: dict, status: dict) -> str:
    fill = {"STAMPED": "#0E6B5E,color:#fff", "GREEN": "#3f8f5f,color:#fff",
            "STALE": "#9A6510,color:#fff", "BLOCKED": "#8E2438,color:#fff",
            "TODO": "#5a6468,color:#fff"}
    out = ["```mermaid", "graph LR"]
    for g, label in GROUPS.items():
        ids = [i for i, n in nodes.items() if n.get("group") == g]
        if not ids:
            continue
        out.append(f'  subgraph {g}["{label}"]')
        for i in ids:
            st = status[i][0]
            mark = {"STAMPED": "✓", "GREEN": "·", "STALE": "!",
                    "BLOCKED": "✗", "TODO": "○"}[st]
            out.append(f'    {i}["{mark} {nodes[i]["name"]}"]')
        out.append("  end")
    for i, n in nodes.items():
        for d in n.get("deps", []):
            if d in nodes:
                out.append(f"  {d} --> {i}")
    for i in nodes:
        out.append(f"  style {i} fill:{fill[status[i][0]]}")
    out.append("```")
    return "\n".join(out)


def table(nodes: dict, status: dict) -> str:
    rows = ["| | node | status | evidence |", "|---|---|---|---|"]
    for i, n in nodes.items():
        st, note = status[i]
        cls = "" if n.get("class") == "implementation" else " **fidelity**"
        rows.append(f"| `{i}` | {n['name']}{cls} | **{st}** | {note} |")
    return "\n".join(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any node is STALE, or if README is out of date")
    ap.add_argument("--print", action="store_true", help="write to stdout, not README")
    args = ap.parse_args()

    nodes = json.loads(DAG.read_text())["nodes"]
    status = {i: classify(i, n) for i, n in nodes.items()}

    # The fidelity audit: a subsystem whose only evidence is against our own
    # model is UNVALIDATED, however many tests pass. Issue #45.
    warn = []
    for g in NEEDS_FIDELITY:
        ids = [i for i, n in nodes.items() if n.get("group") == g]
        fid = [i for i in ids if nodes[i].get("class") == "fidelity"
               and status[i][0] in ("GREEN", "STAMPED")]
        if ids and not fid:
            warn.append(f"{GROUPS[g]}: no green fidelity evidence -- UNVALIDATED "
                        f"against anything external")

    body = [mermaid(nodes, status), "", table(nodes, status)]
    if warn:
        body += ["", "> **Unvalidated subsystems.** " + "  \n> ".join(warn)]
    body += ["", f"<sub>Compiled from `docs/dag.json` by `tools/compile_dag.py` at "
                 f"`{git('rev-parse', '--short', 'HEAD') or 'unknown'}`. "
                 f"Status is derived from evidence, not asserted.</sub>"]
    block = "\n".join(body)

    if args.print:
        print(block)
    else:
        txt = README.read_text()
        if BEGIN not in txt:
            print(f"README.md has no {BEGIN} marker", file=sys.stderr)
            return 2
        new = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END),
                     f"{BEGIN}\n{block}\n{END}", txt, flags=re.S)
        if args.check and new != txt:
            print("README.md is out of date -- run tools/compile_dag.py", file=sys.stderr)
            return 1
        README.write_text(new)

    stale = [i for i in nodes if status[i][0] == "STALE"]
    for i in stale:
        print(f"STALE: {i} -- {status[i][1]}", file=sys.stderr)
    for w in warn:
        print(f"note: {w}", file=sys.stderr)
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    sys.exit(main())
