"""awg-sitecheck command line.

  awg-sitecheck probe    [--sites sites.yaml] [SITE ...] [--deep] [--direct] [--headless]
  awg-sitecheck verify   MERCHANT.json ... [--card card.json] [harness args]      (level 2, see harness/README.md)
  awg-sitecheck purchase SITE [--purchase --max-total 30.00]                       (level 3)
  awg-sitecheck adapter  apply|plan|teardown SPEC.yaml
  awg-sitecheck adapter  dry-run SPEC.yaml FUNCTION_KEY FIXTURE.json
  awg-sitecheck adapter  list
  awg-sitecheck report   RUN_DIR
"""
import argparse
import json
import os
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

from . import adapters, config, probe, purchase, report
from .api import Api

ROOT = Path(__file__).resolve().parent.parent


def _run_root(args, kind):
    root = Path(args.out or "runs") / f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def cmd_probe(args):
    cfg = config.load(args.sites)
    api = Api(cfg)
    root = _run_root(args, "probe")
    for site in cfg.select(args.site):
        print(f"== {site.id}: {site.name}", flush=True)
        r = probe.probe_site(api, cfg, site, root / site.id, deep=args.deep, direct=args.direct, headless=args.headless)
        print(f"   {r['verdict']}  walls={r.get('bot_walls')}  psps={[p['psp'] for p in r.get('psps', [])]}"
              + (f"  error={r['error']}" if r.get("error") else ""), flush=True)
    sc = report.write(root)
    print(f"\nscorecard: {sc}\nhtml:      {root / 'scorecard.html'}")


def cmd_purchase(args):
    cfg = config.load(args.sites)
    site = cfg.site(args.site)
    root = _run_root(args, "purchase")
    r = purchase.run_purchase(Api(cfg), cfg, site, root / site.id, purchase=args.purchase,
                              max_total=Decimal(args.max_total) if args.max_total else None, headless=args.headless)
    shown = {k: v for k, v in r.items() if k != "trace"}
    print(json.dumps(shown, indent=1, default=str))
    sys.exit(0 if not r.get("error") else 1)


def cmd_verify(args, rest):
    cfg = config.load(args.sites)
    api = Api(cfg)
    env = dict(os.environ, VGS_API=cfg.endpoints["api"], VGS_TENANT=cfg.tenant, VGS_ACCESS_TOKEN=api.token())
    harness = next((d / "harness" / "awg_harness.py" for d in (ROOT, Path.cwd())
                    if (d / "harness" / "awg_harness.py").exists()), None)
    if not harness:
        config.die("harness/awg_harness.py not found: run from the awg-sitecheck folder (uv run awg-sitecheck ...)")
    sys.exit(subprocess.call([sys.executable, str(harness), "verify", *rest], env=env))


def cmd_adapter(args):
    cfg = config.load(args.sites)
    api = Api(cfg)
    if args.action == "list":
        print(json.dumps(adapters.list_live(api), indent=1))
    elif args.action in ("apply", "plan"):
        r = adapters.apply(api, cfg, args.spec, dry_run=args.action == "plan")
        print("\n".join(r["plan"]))
        if r.get("state"):
            print(json.dumps(r["state"], indent=1))
    elif args.action == "teardown":
        print("\n".join(adapters.teardown(api, cfg, args.spec)))
    elif args.action == "dry-run":
        a = adapters.dry_run(api, cfg, args.spec, args.function, args.fixture)
        print(json.dumps(a, indent=1))
        sys.exit(0 if a.get("status") == "succeeded" else 1)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(prog="awg-sitecheck", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sites", default=os.environ.get("AWG_SITES", "sites.yaml"))
    p.add_argument("--out", default=os.environ.get("AWG_RUNS"))
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("probe", help="level 1: reachability, bot walls, payment provider")
    sp.add_argument("site", nargs="*")
    sp.add_argument("--deep", action="store_true", help="run each site's recipe up to the card form")
    sp.add_argument("--direct", action="store_true", help="also load the URLs through the egress proxy only")
    sp.add_argument("--headless", action="store_true")

    sub.add_parser("verify", help="level 2: adapter crypto check (harness/awg_harness.py verify ...)", add_help=False)

    sp = sub.add_parser("purchase", help="level 3: recorded checkout; stops before the order unless --purchase")
    sp.add_argument("site")
    sp.add_argument("--purchase", action="store_true", help="place the order (needs --max-total)")
    sp.add_argument("--max-total", help="the most this order may cost, e.g. 30.00")
    sp.add_argument("--headless", action="store_true")

    sp = sub.add_parser("adapter", help="functions, adapters and bindings as code")
    sp.add_argument("action", choices=["apply", "plan", "teardown", "dry-run", "list"])
    sp.add_argument("spec", nargs="?")
    sp.add_argument("function", nargs="?")
    sp.add_argument("fixture", nargs="?")

    sp = sub.add_parser("report", help="rebuild the scorecard of a probe run")
    sp.add_argument("run_dir")

    if argv[:1] == ["verify"] or (len(argv) > 2 and "verify" in argv and argv.index("verify") <= 4):
        i = argv.index("verify")
        args = p.parse_args(argv[:i] + ["report", "."])  # parse the global options only
        return cmd_verify(args, argv[i + 1:])
    args = p.parse_args(argv)
    if args.cmd == "probe":
        cmd_probe(args)
    elif args.cmd == "purchase":
        cmd_purchase(args)
    elif args.cmd == "adapter":
        if args.action != "list" and not args.spec:
            p.error("adapter: SPEC.yaml required")
        cmd_adapter(args)
    elif args.cmd == "report":
        print(report.write(args.run_dir))


if __name__ == "__main__":
    main()
