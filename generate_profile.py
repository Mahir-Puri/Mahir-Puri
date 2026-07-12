"""
Neofetch-style GitHub profile SVG generator.

Runs daily via GitHub Actions. Pulls live stats from the GitHub API
(commits, stars, repos, followers, lines of code) and renders them
into profile_dark.svg alongside ASCII art.

Requires the ACCESS_TOKEN env var (a classic PAT with `repo` + `read:user`).
"""

import datetime
import hashlib
import json
import os
import sys
import time
from dateutil import relativedelta

import requests

# ---------------------------------------------------------------- config

USERNAME = "Mahir-Puri"
BIRTHDAY = datetime.datetime(2006, 10, 17)
PANEL_WIDTH = 58          # character width of the right-hand info panel
LINE_HEIGHT = 17          # px between text rows in the SVG
FONT_SIZE = 13
CHAR_W = 7.8              # approx monospace char width at 13px
CACHE_PATH = "cache/loc_cache.json"
OUTPUT_SVG = "profile_dark.svg"
ASCII_PATH = "ascii_art.txt"

TOKEN = os.environ.get("ACCESS_TOKEN")
HEADERS = {"Authorization": f"token {TOKEN}"} if TOKEN else {}

GQL = "https://api.github.com/graphql"
REST = "https://api.github.com"

# GitHub-dark palette
C = {
    "bg": "#0d1117",
    "border": "#30363d",
    "ascii": "#8b949e",
    "user": "#e3b341",     # gold — a small RBC nod
    "rule": "#484f58",
    "key": "#ffa657",
    "dots": "#6e7681",
    "val": "#c9d1d9",
    "add": "#3fb950",
    "del": "#f85149",
    "dim": "#8b949e",
}


# ---------------------------------------------------------------- fetchers

def gql(query, variables):
    for attempt in range(3):
        r = requests.post(GQL, json={"query": query, "variables": variables}, headers=HEADERS, timeout=30)
        if r.status_code == 200 and "errors" not in r.json():
            return r.json()["data"]
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GraphQL failed: {r.status_code} {r.text[:300]}")


def fetch_user_core():
    q = """
    query($login: String!) {
      user(login: $login) {
        createdAt
        followers { totalCount }
        repositories(first: 100, ownerAffiliations: OWNER, isFork: false) {
          totalCount
          nodes { nameWithOwner stargazerCount pushedAt isPrivate }
        }
        repositoriesContributedTo(first: 1, contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY]) {
          totalCount
        }
      }
    }"""
    return gql(q, {"login": USERNAME})["user"]


def fetch_total_commits(created_at):
    """Sum commit contributions year by year since account creation."""
    q = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          restrictedContributionsCount
        }
      }
    }"""
    start = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    now = datetime.datetime.now(datetime.timezone.utc)
    total = 0
    cursor = start
    while cursor < now:
        end = min(cursor + datetime.timedelta(days=365), now)
        c = gql(q, {
            "login": USERNAME,
            "from": cursor.isoformat(),
            "to": end.isoformat(),
        })["user"]["contributionsCollection"]
        total += c["totalCommitContributions"] + c["restrictedContributionsCount"]
        cursor = end
    return total


def fetch_loc(repos):
    """
    Lines of code added/deleted by USERNAME across owned repos, using the
    contributor-stats endpoint. Results are cached per repo+pushedAt so
    unchanged repos cost nothing on subsequent runs.
    """
    cache = {}
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            cache = json.load(f)

    add = delete = 0
    fresh = {}
    for repo in repos:
        name = repo["nameWithOwner"]
        key = hashlib.sha1(f"{name}:{repo['pushedAt']}".encode()).hexdigest()
        if key in cache:
            a, d = cache[key]
        else:
            a, d = loc_for_repo(name)
        fresh[key] = [a, d]
        add += a
        delete += d

    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(fresh, f)
    return add, delete


def loc_for_repo(name_with_owner):
    """Contributor stats return 202 while GitHub computes them; poll briefly."""
    url = f"{REST}/repos/{name_with_owner}/stats/contributors"
    for _ in range(8):
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 202:
            time.sleep(4)
            continue
        if r.status_code != 200:
            return 0, 0
        add = delete = 0
        for contributor in r.json() or []:
            if contributor.get("author", {}).get("login") == USERNAME:
                for week in contributor.get("weeks", []):
                    add += week.get("a", 0)
                    delete += week.get("d", 0)
        return add, delete
    return 0, 0


# ---------------------------------------------------------------- layout

def uptime():
    diff = relativedelta.relativedelta(datetime.datetime.now(), BIRTHDAY)
    return "{} years, {} months, {} days".format(diff.years, diff.months, diff.days)


def leader(key, value, key_color=None):
    """'. Key: ...dots... value' with the value right-aligned to PANEL_WIDTH."""
    left = f". {key}: "
    n = PANEL_WIDTH - len(left) - len(value) - 1
    dots = "." * max(n, 1)
    return [
        (left, key_color or C["key"]),
        (dots + " ", C["dots"]),
        (value, C["val"]),
    ]


def rule(label):
    """'- Label ————…' section divider."""
    left = f"- {label} "
    dashes = "\u2500" * max(PANEL_WIDTH - len(left), 1)
    return [(left, C["key"]), (dashes, C["rule"])]


def build_panel(stats):
    fmt = "{:,}".format
    loc_net = fmt(stats["loc_add"] - stats["loc_del"])
    lines = []

    head = "mahir@puri "
    lines.append([(head, C["user"]),
                  ("\u2500" * (PANEL_WIDTH - len(head)), C["rule"])])
    lines.append(leader("OS", "macOS, Ubuntu, Azure Databricks, AWS"))
    lines.append(leader("Uptime", stats["uptime"]))
    lines.append(leader("Host", "University of Victoria, BSEng '28"))
    lines.append(leader("Kernel", "Software Engineer (Co-op Build)"))
    lines.append(leader("Next.Deploy", "RBC Real-Time Payments, Fall 2026"))
    lines.append([(".", C["dots"])])
    lines.append(leader("Languages.Programming", "Java, Python, TS, C++, Ruby"))
    lines.append(leader("Languages.Markup", "SQL, HTML, CSS, YAML, LaTeX"))
    lines.append(leader("Languages.Real", "English"))
    lines.append([(".", C["dots"])])
    lines.append(leader("Systems.Fintech", "RTPN Rail, Flash Sale Engine"))
    lines.append(leader("Systems.AI", "Adversary Red-Team CI, RAG"))
    lines.append(leader("Daemons.Background", "PRAYAS, Sewa UVic"))
    lines.append([("", C["dots"])])

    lines.append(rule("Contact"))
    lines.append(leader("Email", "mahirpuri.17@gmail.com"))
    lines.append(leader("Portfolio", "mahir-portfolio-three.vercel.app"))
    lines.append(leader("LinkedIn", "in/mahir-puri"))
    lines.append([("", C["dots"])])

    lines.append(rule("GitHub Stats"))

    # Repos {Contributed} | Stars
    left_val = f"{stats['repos']} {{Contributed: {stats['contributed']}}}"
    lines.append(split_stat("Repos", left_val, "Stars", fmt(stats["stars"])))
    lines.append(split_stat("Commits", fmt(stats["commits"]), "Followers", fmt(stats["followers"])))

    loc_left = f". Lines of Code on GitHub: "
    loc_total = loc_net + " ( "
    lines.append([
        (loc_left, C["key"]),
        (loc_total.rjust(0), C["val"]),
        (fmt(stats["loc_add"]) + "++", C["add"]),
        (", ", C["val"]),
        (fmt(stats["loc_del"]) + "--", C["del"]),
        (" )", C["val"]),
    ])
    return lines


def split_stat(k1, v1, k2, v2):
    """Two stats on one line separated by a pipe, dot-padded like neofetch."""
    half = PANEL_WIDTH // 2
    l1 = f". {k1}: "
    n1 = half - len(l1) - len(v1) - 1
    l2 = f" {k2}: "
    n2 = PANEL_WIDTH - half - len(l2) - len(v2) - 3
    return [
        (l1, C["key"]), ("." * max(n1, 1) + " ", C["dots"]), (v1, C["val"]),
        (" |", C["rule"]),
        (l2, C["key"]), ("." * max(n2, 1) + " ", C["dots"]), (v2, C["val"]),
    ]


# ---------------------------------------------------------------- svg

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_svg(ascii_lines, panel_lines):
    pad = 28
    ascii_w = max(len(l) for l in ascii_lines) * CHAR_W
    panel_x = pad + ascii_w + 34
    width = int(panel_x + PANEL_WIDTH * CHAR_W + pad)
    rows = max(len(ascii_lines), len(panel_lines))
    height = int(pad * 2 + rows * LINE_HEIGHT)

    # vertically center the shorter column
    ascii_y0 = pad + 4 + ((rows - len(ascii_lines)) * LINE_HEIGHT) // 2
    panel_y0 = pad + 4 + ((rows - len(panel_lines)) * LINE_HEIGHT) // 2

    font = "'JetBrains Mono','Fira Code','Consolas','Liberation Mono',monospace"
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="{font}" font-size="{FONT_SIZE}px">',
        f'<rect x="0.5" y="0.5" width="{width-1}" height="{height-1}" rx="10" '
        f'fill="{C["bg"]}" stroke="{C["border"]}"/>',
    ]

    for i, line in enumerate(ascii_lines):
        y = ascii_y0 + i * LINE_HEIGHT + LINE_HEIGHT
        out.append(
            f'<text x="{pad}" y="{y}" xml:space="preserve" fill="{C["ascii"]}">{esc(line)}</text>'
        )

    for i, segments in enumerate(panel_lines):
        y = panel_y0 + i * LINE_HEIGHT + LINE_HEIGHT
        spans = "".join(
            f'<tspan fill="{color}">{esc(text)}</tspan>' for text, color in segments if text
        )
        out.append(f'<text x="{int(panel_x)}" y="{y}" xml:space="preserve">{spans}</text>')

    out.append("</svg>")
    return "\n".join(out)


# ---------------------------------------------------------------- main

def main():
    with open(ASCII_PATH) as f:
        ascii_lines = f.read().rstrip("\n").split("\n")

    if not TOKEN:
        print("ACCESS_TOKEN not set — rendering with placeholder stats.")
        stats = {
            "uptime": uptime(), "repos": 16, "contributed": 20, "stars": 2,
            "commits": 500, "followers": 7, "loc_add": 100000, "loc_del": 20000,
        }
    else:
        user = fetch_user_core()
        repos = user["repositories"]["nodes"]
        stats = {
            "uptime": uptime(),
            "repos": user["repositories"]["totalCount"],
            "contributed": user["repositoriesContributedTo"]["totalCount"],
            "stars": sum(r["stargazerCount"] for r in repos),
            "followers": user["followers"]["totalCount"],
            "commits": fetch_total_commits(user["createdAt"]),
        }
        stats["loc_add"], stats["loc_del"] = fetch_loc(repos)

    svg = render_svg(ascii_lines, build_panel(stats))
    with open(OUTPUT_SVG, "w") as f:
        f.write(svg)
    print(f"Wrote {OUTPUT_SVG}")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    sys.exit(main())
