#!/usr/bin/env python3
"""Phase 7: verify_abis.py — read-only ABI-verification auditor.

Cross-checks the honest catalog in ``ABI_VERIFICATION_NEEDED.md`` against the
actual service sources under ``runtime/blockchain/services/*/service.py`` and
reports what a human still has to confirm against real deployed contracts
before flipping each service on.

It is an AUDIT, not a fix — it changes no ABIs, signs nothing, and makes no
network call. Two independent signals are reconciled:

  1. **Doc coverage** — every service that carries an ``UNVERIFIED`` flag in
     its source SHOULD have a section in ABI_VERIFICATION_NEEDED.md (and vice
     versa). A drift either way is flagged: an undocumented UNVERIFIED service
     could get flipped on without review; a documented-but-clean service may
     have had its flag silently dropped.
  2. **Config-gated safety** — a service with UNVERIFIED ABIs must stay a
     credential-gated no-op until verified. The doc records the config key(s);
     this lists them so an operator knows exactly what NOT to fill yet.

Usage:
    python scripts/verify_abis.py            # human-readable report
    python scripts/verify_abis.py --json     # machine-readable
    python scripts/verify_abis.py --strict   # exit 1 on any doc/source drift
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "ABI_VERIFICATION_NEEDED.md"
SERVICES = ROOT / "runtime" / "blockchain" / "services"


def documented_services() -> dict[str, int]:
    """Map service name -> count of UNVERIFIED mentions in its doc section.

    Section headers look like ``### 3. mpc (recovery / session keys ...)`` —
    the service name is the first token after the number.
    """
    out: dict[str, int] = {}
    if not DOC.exists():
        return out
    current = None
    for line in DOC.read_text().splitlines():
        m = re.match(r"^###\s+\d+\.\s+([a-z_]+)", line)
        if m:
            current = m.group(1)
            out[current] = 0
        elif current and "UNVERIFIED" in line:
            out[current] += 1
    return out


def source_unverified() -> dict[str, int]:
    """Map service dir name -> count of UNVERIFIED flags in its service.py."""
    out: dict[str, int] = {}
    if not SERVICES.exists():
        return out
    for svc_dir in sorted(SERVICES.iterdir()):
        svc = svc_dir / "service.py"
        if not svc.is_file():
            continue
        n = svc.read_text().count("UNVERIFIED")
        if n:
            out[svc_dir.name] = n
    return out


def config_keys_for(service: str) -> list[str]:
    """Pull the ``services.<name>.<key>`` config keys named in the doc section."""
    if not DOC.exists():
        return []
    text = DOC.read_text()
    m = re.search(rf"^###\s+\d+\.\s+{re.escape(service)}\b(.*?)(?=^###\s|\Z)",
                  text, re.S | re.M)
    if not m:
        return []
    keys = re.findall(r"services\.[a-z_]+\.[a-z_]+", m.group(1))
    return sorted(set(keys))


def audit() -> dict:
    doc = documented_services()
    src = source_unverified()

    # Drift is only the two DANGEROUS mismatches:
    #  - undocumented: source carries UNVERIFIED flags but has NO doc section
    #    at all → it could be flipped on without review.
    #  - dropped_flag: the doc section CLAIMS UNVERIFIED (>=1 mention) but the
    #    source now has zero → a flag was silently removed; re-check.
    # A doc section with zero UNVERIFIED mentions and a clean source is
    # legitimately "documented & verified" (e.g. tba/ERC-6551) — NOT drift.
    src_names = set(src)
    doc_names = set(doc)
    undocumented = sorted(n for n in src_names if n not in doc_names)
    dropped_flag = sorted(n for n in doc_names
                          if doc.get(n, 0) > 0 and src.get(n, 0) == 0)

    services = []
    for name in sorted(src_names | doc_names):
        s_n, d_n = src.get(name, 0), doc.get(name, 0)
        if name in undocumented:
            status = "UNDOCUMENTED (source UNVERIFIED but no doc section)"
        elif name in dropped_flag:
            status = "DROPPED-FLAG (doc claims UNVERIFIED but source has none)"
        elif d_n == 0 and s_n == 0:
            status = "DOCUMENTED-CLEAN (verified / low-risk)"
        else:
            status = "OK"
        services.append({
            "service": name,
            "source_unverified": s_n,
            "doc_section": name in doc,
            "doc_unverified_mentions": d_n,
            "config_keys_to_leave_unset": config_keys_for(name),
            "status": status,
        })

    return {
        "total_documented_services": len(doc),
        "total_source_unverified_services": len(src),
        "undocumented": undocumented,
        "dropped_flag": dropped_flag,
        "services": services,
        "drift": bool(undocumented or dropped_flag),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only ABI-verification auditor")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if the doc and the source flags have drifted")
    args = ap.parse_args()

    report = audit()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("verify_abis — ABI-verification audit (read-only, no network, no signing)\n")
        print(f"  documented services:        {report['total_documented_services']}")
        print(f"  source UNVERIFIED services: {report['total_source_unverified_services']}\n")
        for s in report["services"]:
            flag = "❌" if s["status"].split()[0] in ("UNDOCUMENTED", "DROPPED-FLAG") else "✅"
            print(f"  {flag} {s['service']:22} src={s['source_unverified']:<2} "
                  f"doc={s['doc_unverified_mentions']:<2} {s['status']}")
            if s["config_keys_to_leave_unset"] and s["source_unverified"]:
                print(f"       leave unset until verified: "
                      f"{', '.join(s['config_keys_to_leave_unset'])}")
        print()
        if report["drift"]:
            if report["undocumented"]:
                print(f"UNDOCUMENTED (add a doc section before go-live): "
                      f"{', '.join(report['undocumented'])}")
            if report["dropped_flag"]:
                print(f"DROPPED-FLAG (doc claims UNVERIFIED, source clean — re-check): "
                      f"{', '.join(report['dropped_flag'])}")
        else:
            print("No drift: every source UNVERIFIED service is documented, "
                  "and every doc UNVERIFIED claim is still present in source.")

    return 1 if (args.strict and report["drift"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
