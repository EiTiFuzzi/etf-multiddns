"""
Optionales CLI fuer den Container, z.B. via:

  docker exec -it etf-multiddns python -m app.cli list
  docker exec -it etf-multiddns python -m app.cli add --domain beispiel.at --name home --type A
  docker exec -it etf-multiddns python -m app.cli remove <record-id>
  docker exec -it etf-multiddns python -m app.cli sync

Nuetzlich, wenn man die Records nicht ueber das Web-UI, sondern per Skript /
SSH verwalten moechte.
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import config as config_module
from .ddns import DDNSService

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main() -> int:
    parser = argparse.ArgumentParser(prog="etf-multiddns")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Alle konfigurierten Records anzeigen")

    add_p = sub.add_parser("add", help="Neuen Record hinzufuegen")
    add_p.add_argument("--domain", required=True)
    add_p.add_argument("--name", default="", help="Subdomain, leer = Root-Domain")
    add_p.add_argument("--type", choices=["A", "AAAA"], default="A")
    add_p.add_argument("--ttl", type=int, default=300)
    add_p.add_argument("--comment", default="Managed by etf-multiddns")
    add_p.add_argument(
        "--provider", choices=["domainchief", "cloudflare"], default="domainchief",
        help="DNS-Provider (Standard: domainchief)",
    )
    add_p.add_argument(
        "--proxied", action="store_true",
        help="Nur Cloudflare: Record ueber Cloudflares Proxy laufen lassen (orange Wolke)",
    )

    remove_p = sub.add_parser("remove", help="Record entfernen (lokal + bei Domain Chief)")
    remove_p.add_argument("record_id")

    sub.add_parser("sync", help="Sofort einen Sync-Durchlauf ausfuehren")

    args = parser.parse_args()
    service = DDNSService()

    if args.command == "list":
        service.reload_config()
        records = service.config.get("records", [])
        if not records:
            print("Keine Records konfiguriert.")
            return 0
        for r in records:
            host = f"{r['name']}.{r['domain']}" if r["name"] else r["domain"]
            provider = r.get("provider", "domainchief")
            print(f"{r['id']}\t{host}\t{r['type']}\tprovider={provider}\tstatus={r['last_status']}\tip={r.get('last_ip')}")
        return 0

    if args.command == "add":
        record = config_module.add_record(
            service.config, domain=args.domain, name=args.name, record_type=args.type, ttl=args.ttl,
            comment=args.comment, provider=args.provider, proxied=args.proxied,
        )
        print(f"Record hinzugefuegt: {record['id']}")
        return 0

    if args.command == "remove":
        try:
            service.delete_record_remote_and_local(args.record_id)
            print("Record entfernt.")
            return 0
        except KeyError:
            print(f"Kein Record mit ID {args.record_id} gefunden.", file=sys.stderr)
            return 1

    if args.command == "sync":
        summary = service.sync_once()
        print(summary)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
