#!/usr/bin/env python
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


DEFAULT_URL = "https://rednews.onrender.com"


def request(method, path, payload=None, admin=False):
    base_url = os.environ.get("REDNEWS_URL", DEFAULT_URL).rstrip("/")
    headers = {"Accept": "application/json"}
    data = None

    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    if admin:
        key = os.environ.get("ADMIN_API_KEY")
        if not key:
            raise SystemExit("Defina ADMIN_API_KEY no ambiente antes de alterar notícias.")
        headers["X-Admin-Key"] = key

    req = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Erro {exc.code}: {detail}") from exc


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Gerencia notícias da Red News via API segura.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="Lista notícias publicadas.")

    add = sub.add_parser("add", help="Cria notícia a partir de um JSON.")
    add.add_argument("json_file")

    update = sub.add_parser("update", help="Atualiza notícia a partir de um JSON.")
    update.add_argument("news_id")
    update.add_argument("json_file")

    delete = sub.add_parser("delete", help="Remove notícia pelo ID.")
    delete.add_argument("news_id")

    args = parser.parse_args()

    if args.cmd == "list":
        news = request("GET", "/api/news")
        for item in news:
            print(f"{item['id']}\t{item.get('cat','')}\t{item.get('title','')}")
        return

    if args.cmd == "add":
        result = request("POST", "/api/news", load_json(args.json_file), admin=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.cmd == "update":
        result = request("PUT", f"/api/news/{args.news_id}", load_json(args.json_file), admin=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.cmd == "delete":
        result = request("DELETE", f"/api/news/{args.news_id}", admin=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
