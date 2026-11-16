"""Scorecards: one Markdown and one HTML table across all probed sites of a run."""
import html
import json
from pathlib import Path


def _row(r):
    pages = r.get("pages", [])
    statuses = " ".join(str(p.get("status")) + (f"({p['blocked']})" if p.get("blocked") else "") for p in pages)
    direct = " ".join(str(p.get("status")) + (f"({p['blocked']})" if p.get("blocked") else "")
                      for p in r.get("direct_pages") or [])
    psps = ", ".join(p["psp"] + (" (CSE)" if p["client_side_encryption"] else "") for p in r.get("psps", []))
    deep = r.get("deep") or {}
    cap = deep.get("captured")
    return {
        "site": r.get("site"), "verdict": r.get("verdict"), "via gateway": statuses or "-",
        "direct": direct or "-", "bot walls": ", ".join(r.get("bot_walls", [])) or "-", "payment": psps or "?",
        "card form": ("yes" if deep.get("reached_payment") else ("no" if deep else "-")),
        "key captured": ("-" if cap is None else ("yes" if all(cap.values()) else "no")),
        "exit": ", ".join(str(v) for v in (r.get("exit_ip") or {}).values() if v)[:40] or "-",
        "error": (r.get("error") or deep.get("error") or "")[:120],
    }


def write(run_root):
    run_root = Path(run_root)
    results = [json.loads(p.read_text()) for p in sorted(run_root.glob("*/result.json"))]
    rows = [_row(r) for r in results]
    if not rows:
        return None
    cols = list(rows[0])
    md = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    md += ["| " + " | ".join(str(r[c]).replace("|", "/") for c in cols) + " |" for r in rows]
    counts = {}
    for r in rows:
        k = (r["verdict"] or "?").split(";")[0]
        counts[k] = counts.get(k, 0) + 1
    summary = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    (run_root / "scorecard.md").write_text(f"# AWG site probe\n\n{len(rows)} sites. {summary}\n\n" + "\n".join(md) + "\n")
    th = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    trs = "".join("<tr>" + "".join(f"<td>{html.escape(str(r[c]))}</td>" for c in cols) + "</tr>" for r in rows)
    (run_root / "scorecard.html").write_text(
        "<!doctype html><meta charset=utf-8><title>AWG site probe</title><style>body{font:14px system-ui;margin:24px}"
        "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px 8px;text-align:left;vertical-align:top}"
        f"th{{background:#f3f4f6}}</style><h1>AWG site probe</h1><p>{len(rows)} sites. {html.escape(summary)}</p>"
        f"<table><tr>{th}</tr>{trs}</table>")
    return run_root / "scorecard.md"
