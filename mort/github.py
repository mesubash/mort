import json
import subprocess
from datetime import datetime, timezone

INTERVAL = 300  # GitHub rate limits; replies are not minute-urgent


def gh(path, **params):
    args = ["gh", "api", "-X", "GET", path]
    for k, v in params.items():
        args += ["-f", f"{k}={v}"]
    out = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "gh api failed")
    return json.loads(out.stdout)


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def replies(since, api=gh):
    """Comments and reviews by other people on the user's open issues and pull requests after `since` (ISO)."""
    me = api("user")["login"]
    found = []
    for item in api("search/issues", q=f"author:{me} state:open updated:>{since}", per_page=100)["items"]:
        repo = item["repository_url"].split("/repos/", 1)[1]
        n = item["number"]
        posts = api(f"repos/{repo}/issues/{n}/comments", since=since, per_page=100)
        if "pull_request" in item:
            posts += api(f"repos/{repo}/pulls/{n}/comments", since=since, per_page=100)
            posts += [dict(r, created_at=r.get("submitted_at") or "") for r in api(f"repos/{repo}/pulls/{n}/reviews", per_page=100)]
        for p in posts:
            user = p.get("user") or {}
            if user.get("login") == me or user.get("type") == "Bot" or p.get("created_at", "") <= since:
                continue
            text = " ".join((p.get("body") or p.get("state", "").lower() or "").split())
            found.append({"where": f"{repo}#{n}", "who": user.get("login", "?"), "text": text[:100],
                          "at": p["created_at"], "url": p.get("html_url") or item["html_url"]})
    return sorted(found, key=lambda r: r["at"])


def check(db, notify, now, api=gh):
    row = db.execute("SELECT value FROM alerts WHERE key = 'github'").fetchone()
    if row is None:
        return
    st = json.loads(row["value"])
    if now - st.get("checked", 0) < INTERVAL:
        return
    try:
        new = replies(st["since"], api)
    except (RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as e:
        st.update(checked=now, error=str(e)[:200])  # shown in the summary; retried next interval
    else:
        for r in new:
            notify(f"reply on {r['where']} from {r['who']}", r["text"])
        st.update(checked=now, since=new[-1]["at"] if new else st["since"], error=None,
                  recent=(st.get("recent", []) + new)[-5:])
    db.execute("UPDATE alerts SET value = ? WHERE key = 'github'", (json.dumps(st),))


def enable(db, now):
    db.execute("INSERT OR IGNORE INTO alerts VALUES ('github', ?)", (json.dumps({"since": iso(now), "checked": 0}),))


def summary(db, now):
    row = db.execute("SELECT value FROM alerts WHERE key = 'github'").fetchone()
    if row is None:
        return []
    st = json.loads(row["value"])
    when = f"checked {int(now - st['checked']) // 60}m ago" if st.get("checked") else "not checked yet"
    lines = ["GITHUB", f"   your open issues and pull requests, {when}" + (f", error: {st['error']}" if st.get("error") else "")]
    lines += [f"   {r['at'][5:16].replace('T', ' ')}  {r['where']}  {r['who']}: {r['text'][:60]}" for r in st.get("recent", [])]
    return lines
