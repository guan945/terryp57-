#!/usr/bin/env python3
"""Sync inbox/*.json (xueqiu posts) into Notion database. Stdlib only."""
import json, os, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
NOTION = "https://api.notion.com/v1"
VERSION = "2022-06-28"
DB_ID_FILE = "state/notion-db.id"

def api(method, path, data=None, token=None):
    url = NOTION + path
    body = json.dumps(data).encode() if data is not None else None
    headers = {"Authorization": "Bearer " + token, "Notion-Version": VERSION}
    if body is not None:
        headers["Content-Type"] = "application/json"
    last = ""
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            last = raw[:300]
            if e.code == 429:
                wait = float(e.headers.get("Retry-After") or 2)
                time.sleep(min(wait, 30)); continue
            if e.code >= 500 and attempt < 4:
                time.sleep(2 * (attempt + 1)); continue
            if e.code == 400 and "rate" in raw.lower() and attempt < 4:
                time.sleep(3); continue
            raise RuntimeError("Notion %s %s -> HTTP %s: %s" % (method, path[:60], e.code, last))
        except Exception as e:
            last = str(e)
            if attempt < 4:
                time.sleep(2 * (attempt + 1)); continue
            raise
    raise RuntimeError("Notion %s %s retries exhausted: %s" % (method, path[:60], last))

def chunks(t, n=1800):
    t = t or ""
    return [t[i:i+n] for i in range(0, len(t), n)] or [""]

def iso_cst(ms):
    return datetime.fromtimestamp(ms / 1000, CST).isoformat(timespec="seconds")

def fmt_dt(ms):
    return datetime.fromtimestamp(ms / 1000, CST).strftime("%Y-%m-%d %H:%M")

def clean_html(t):
    if not t:
        return ""
    if "<" not in t and "&" not in t:
        return t.strip()
    t = re.sub(r'<img[^>]*(?:title|alt)="([^"]*)"[^>]*/?>', r'\\1', t)
    t = re.sub(r'<img[^>]*/?>', '', t)
    t = re.sub(r'<a[^>]*>(.*?)</a>', r'\\1', t, flags=re.S)
    t = re.sub(r'<br\\s*/?>', '\\n', t, flags=re.I)
    t = re.sub(r'</(?:p|div|blockquote|h[1-6]|li)>', '\\n', t, flags=re.I)
    t = re.sub(r'<[^>]+>', '', t)
    t = t.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    t = re.sub(r'\\n{3,}', '\\n\\n', t)
    return t.strip()

def _para_blocks(text):
    blocks = []
    for seg in (text or "").split("\n"):
        if not seg.strip():
            continue
        for c in chunks(seg.strip(), 1800):
            blocks.append({"object": "block", "type": "paragraph",
                           "paragraph": {"rich_text": [{"type": "text", "text": {"content": c}}]}})
    return blocks or [{"object": "block", "type": "paragraph",
                       "paragraph": {"rich_text": [{"type": "text", "text": {"content": "(空)"}}]}}]

def get_user_cfg(cfg, src):
    users = cfg.get("users", {})
    if src in users:
        u = users[src]
        return u.get("database_title", src + "\u96ea\u7403\u52a8\u6001"), u.get("id_file", "state/notion-db.id")
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "-" for ch in src)[:40] or "user"
    return src + "\u96ea\u7403\u52a8\u6001", "state/notion-db-" + safe + ".id"

def find_or_create_db(token, cfg, src):
    db_title, id_file = get_user_cfg(cfg, src)
    os.makedirs("state", exist_ok=True)
    if os.path.exists(id_file):
        v = open(id_file).read().strip()
        if v:
            try:
                api("GET", "/databases/" + v, token=token)
                return v
            except Exception:
                pass
    parent_page_id = cfg["notion_parent_page_id"]
    cursor = None
    while True:
        path = "/blocks/%s/children?page_size=100" % parent_page_id
        if cursor:
            path += "&start_cursor=" + cursor
        d = api("GET", path, token=token)
        for b in d.get("results", []):
            if b.get("type") == "child_database":
                if b.get("child_database", {}).get("title") == db_title:
                    open(id_file, "w").write(b["id"])
                    print("found existing database for %s: %s" % (src, b["id"]))
                    return b["id"]
        if not d.get("has_more"):
            break
        cursor = d.get("next_cursor")
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "icon": {"type": "emoji", "emoji": "\U0001F4C8"},
        "title": [{"type": "text", "text": {"content": db_title}}],
        "properties": {
            "\u6807\u9898": {"title": {}},
            "\u5e16\u5b50ID": {"number": {"format": "number"}},
            "\u53d1\u5e03\u65f6\u95f4": {"date": {}},
            "\u7c7b\u578b": {"select": {"options": [
                {"name": "\u539f\u521b"}, {"name": "\u56de\u590d/\u5f15\u7528"},
                {"name": "\u8f6c\u53d1"}, {"name": "\u957f\u6587"}]}},
            "\u56de\u590d\u6570": {"number": {"format": "number"}},
            "\u8f6c\u53d1\u6570": {"number": {"format": "number"}},
            "\u70b9\u8d5e\u6570": {"number": {"format": "number"}},
            "\u539f\u6587\u94fe\u63a5": {"url": {}},
        },
    }
    d = api("POST", "/databases", data=payload, token=token)
    dbid = d["id"]
    open(id_file, "w").write(dbid)
    print("created database for %s: %s" % (src, dbid))
    return dbid

def exists(token, db_id, pid):
    q = api("POST", "/databases/%s/query" % db_id,
            data={"filter": {"property": "\u5e16\u5b50ID", "number": {"equals": int(pid)}}, "page_size": 1},
            token=token)
    return bool(q.get("results"))

def rich(c):
    return [{"type": "text", "text": {"content": x}} for x in chunks(c, 1800)]

def create_page(token, db_id, rec):
    c = rec.get("c") or [0, 0, 0]
    txt = clean_html(rec.get("txt") or "")
    title = "%s [%s] %s" % (fmt_dt(rec["ts"]).replace(" ", " "), rec.get("ty", ""), txt[:30])
    props = {
        "\u6807\u9898": {"title": rich(title[:200])},
        "\u5e16\u5b50ID": {"number": int(rec["id"])},
        "\u53d1\u5e03\u65f6\u95f4": {"date": {"start": iso_cst(rec["ts"])}},
        "\u7c7b\u578b": {"select": {"name": rec.get("ty") or "\u539f\u521b"}},
        "\u56de\u590d\u6570": {"number": c[0]},
        "\u8f6c\u53d1\u6570": {"number": c[1]},
        "\u70b9\u8d5e\u6570": {"number": c[2]},
    }
    if rec.get("link"):
        props["\u539f\u6587\u94fe\u63a5"] = {"url": "https://xueqiu.com" + rec["link"]}
    children = []
    if rec.get("title"):
        children += [{"object": "block", "type": "heading_2",
                      "heading_2": {"rich_text": rich(clean_html(rec["title"]))}}]
    children += _para_blocks(txt)
    q = rec.get("q")
    if q and q.get("txt"):
        children += [{"object": "block", "type": "divider", "divider": {}}]
        head = "\u25ce \u5f15\u7528 @%s\uff1a" % q.get("u", "")
        children += [{"object": "block", "type": "quote",
                      "quote": {"rich_text": rich(head + clean_html(q["txt"])[:1500])}}]
    body = {"parent": {"database_id": db_id}, "properties": props}
    if children:
        body["children"] = children[:100]
    api("POST", "/pages", data=body, token=token)

def main():
    cfg = json.load(open("config/config.json"))
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        print("ERROR: NOTION_TOKEN missing"); sys.exit(1)
    os.makedirs("inbox", exist_ok=True)
    os.makedirs("processed", exist_ok=True)
    db_cache = {}
    files = sorted(f for f in os.listdir("inbox") if f.endswith(".json"))
    print("inbox files:", len(files))
    total_created = total_skip = total_err = 0
    failed = []
    for fname in files:
        try:
            recs = json.load(open("inbox/" + fname, encoding="utf-8"))
        except Exception as e:
            print("BAD FILE %s: %s" % (fname, e))
            failed.append(fname); continue
        if isinstance(recs, dict):
            recs = recs.get("records", [])
        fc = fs = fe = 0
        for rec in recs:
            try:
                s = rec.get("src") or "terryp57"
                if s not in db_cache:
                    db_cache[s] = find_or_create_db(token, cfg, s)
                db_id = db_cache[s]
                if exists(token, db_id, rec["id"]):
                    fs += 1
                else:
                    create_page(token, db_id, rec)
                    fc += 1
                time.sleep(0.35)
            except Exception as e:
                fe += 1
                print("REC FAILED id=%s: %s" % (rec.get("id"), str(e)[:200]))
        print("file %s: created=%d skipped=%d errors=%d" % (fname, fc, fs, fe))
        total_created += fc; total_skip += fs; total_err += fe
        if fe == 0:
            os.rename("inbox/" + fname, "processed/" + fname)
        else:
            failed.append(fname)
    print("SUMMARY created=%d skipped=%d errors=%d failed_files=%s" % (total_created, total_skip, total_err, failed))

if __name__ == "__main__":
    main()
