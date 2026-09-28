"""Render the profile's stats, top-languages and activity cards as static SVGs.

Runs in the profile-assets workflow and publishes to the `output` branch, so the
README only ever loads from raw.githubusercontent.com. Stdlib only.

    GITHUB_TOKEN=... python cards.py <out_dir> [user]
"""
import json
import os
import sys
import urllib.request
from datetime import date
from xml.sax.saxutils import escape

QUERY = """
query($login: String!) {
  user(login: $login) {
    followers { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    repositoriesContributedTo(first: 1, contributionTypes: [COMMIT, PULL_REQUEST, ISSUE, REPOSITORY]) { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

BG = "#000000"
FG = "#ffffff"
MUTED = "#c0c0c0"
DIM = "#6e7681"
FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Sans-Serif"
# Monochrome ramp for language bars, brightest first.
SHADES = ["#ffffff", "#d9d9d9", "#b3b3b3", "#8c8c8c", "#6e6e6e", "#555555", "#444444", "#333333"]


def fetch(user, token):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": user}}).encode(),
        headers={"Authorization": f"bearer {token}", "User-Agent": "restneeded-profile-cards"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.load(resp)
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return body["data"]["user"]


def summarize(u):
    repos = u["repositories"]["nodes"]
    langs = {}
    for r in repos:
        for e in r["languages"]["edges"]:
            langs[e["node"]["name"]] = langs.get(e["node"]["name"], 0) + e["size"]
    cc = u["contributionsCollection"]
    days = [d for w in cc["contributionCalendar"]["weeks"] for d in w["contributionDays"]]
    return {
        "stars": sum(r["stargazerCount"] for r in repos),
        "repos": u["repositories"]["totalCount"],
        "commits": cc["totalCommitContributions"] + cc["restrictedContributionsCount"],
        "prs": u["pullRequests"]["totalCount"],
        "issues": u["issues"]["totalCount"],
        "contributed": u["repositoriesContributedTo"]["totalCount"],
        "followers": u["followers"]["totalCount"],
        "year_total": cc["contributionCalendar"]["totalContributions"],
        "langs": sorted(langs.items(), key=lambda kv: -kv[1]),
        "days": [(d["date"], d["contributionCount"]) for d in days],
    }


def fmt(n):
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def svg(w, h, title, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">'
        f"<title>{escape(title)}</title>"
        f"<style>text{{font-family:{FONT}}}.t{{font-size:18px;font-weight:600;fill:{FG}}}"
        f".l{{font-size:14px;fill:{MUTED}}}.v{{font-size:14px;font-weight:700;fill:{FG}}}"
        f".s{{font-size:11px;fill:{DIM}}}</style>"
        f'<rect width="{w}" height="{h}" rx="4" fill="{BG}"/>{body}</svg>'
    )


def stats_card(s):
    rows = [
        ("Total stars", s["stars"]),
        ("Commits (past year)", s["commits"]),
        ("Pull requests", s["prs"]),
        ("Issues", s["issues"]),
        ("Contributed to", s["contributed"]),
        ("Public repos", s["repos"]),
    ]
    body = '<text x="25" y="35" class="t">restneeded // GitHub stats</text>'
    for i, (label, val) in enumerate(rows):
        y = 68 + i * 22
        body += f'<text x="25" y="{y}" class="l">{label}:</text><text x="205" y="{y}" class="v">{fmt(val)}</text>'
    # Ring with the past year's contribution total.
    cx, cy, r = 395, 105, 50
    body += (
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#30363d" stroke-width="6"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{FG}" stroke-width="6"/>'
        f'<text x="{cx}" y="{cy + 2}" text-anchor="middle" style="font-size:24px;font-weight:700;fill:{FG}">{fmt(s["year_total"])}</text>'
        f'<text x="{cx}" y="{cy + 22}" text-anchor="middle" class="s">past year</text>'
    )
    return svg(495, 195, "GitHub stats", body)


def langs_card(s, count=8):
    top = s["langs"][:count]
    total = sum(v for _, v in top) or 1
    width = 445
    body = '<text x="25" y="35" class="t">Most used languages</text>'
    body += f'<mask id="m"><rect x="25" y="52" width="{width}" height="8" rx="4" fill="#fff"/></mask>'
    x = 25.0
    for i, (_, v) in enumerate(top):
        w = width * v / total
        body += f'<rect mask="url(#m)" x="{x:.2f}" y="52" width="{w:.2f}" height="8" fill="{SHADES[i]}"/>'
        x += w
    for i, (name, v) in enumerate(top):
        col, row = i % 2, i // 2
        lx, ly = 25 + col * 225, 88 + row * 25
        body += (
            f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{SHADES[i]}" stroke="#444" stroke-width="0.5"/>'
            f'<text x="{lx + 16}" y="{ly}" class="l">{escape(name)} <tspan class="s">{100 * v / total:.1f}%</tspan></text>'
        )
    return svg(495, 195, "Top languages", body)


def activity_card(s, n=31):
    days = s["days"][-n:]
    w, h = 900, 300
    left, right, top, bottom = 50, 20, 55, 45
    pw, ph = w - left - right, h - top - bottom
    peak = max((c for _, c in days), default=0)
    ymax = max(4, -(-peak // 4) * 4)  # round up to a multiple of 4 for clean gridlines
    step = pw / max(1, len(days) - 1)
    pts = [(left + i * step, top + ph - ph * c / ymax) for i, (_, c) in enumerate(days)]

    body = f'<text x="{w / 2}" y="32" text-anchor="middle" class="t">contribution activity</text>'
    for k in range(5):
        v = ymax * k // 4
        y = top + ph - ph * v / ymax
        body += (
            f'<line x1="{left}" y1="{y:.1f}" x2="{w - right}" y2="{y:.1f}" stroke="#21262d"/>'
            f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" class="s">{v}</text>'
        )
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    if pts:
        area = f"{pts[0][0]:.1f},{top + ph} {line} {pts[-1][0]:.1f},{top + ph}"
        body += (
            f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{FG}" stop-opacity="0.35"/><stop offset="1" stop-color="{FG}" stop-opacity="0"/>'
            f"</linearGradient></defs>"
            f'<polygon points="{area}" fill="url(#g)"/>'
            f'<polyline points="{line}" fill="none" stroke="{FG}" stroke-width="2" stroke-linejoin="round"/>'
        )
    for i, ((x, y), (d, c)) in enumerate(zip(pts, days)):
        body += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{MUTED}"><title>{d}: {c}</title></circle>'
        if i % 5 == 0 or i == len(days) - 1:
            label = date.fromisoformat(d).strftime("%b %d").replace(" 0", " ")
            body += f'<text x="{x:.1f}" y="{h - 18}" text-anchor="middle" class="s">{label}</text>'
    return svg(w, h, "Contribution activity", body)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "dist"
    user = sys.argv[2] if len(sys.argv) > 2 else "restneeded"
    s = summarize(fetch(user, os.environ["GITHUB_TOKEN"]))
    os.makedirs(out, exist_ok=True)
    for name, doc in (("stats.svg", stats_card(s)), ("top-langs.svg", langs_card(s)), ("activity.svg", activity_card(s))):
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            f.write(doc)
        print(f"wrote {name} ({len(doc)} bytes)")


if __name__ == "__main__":
    main()
