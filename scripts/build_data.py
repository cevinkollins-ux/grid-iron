#!/usr/bin/env python3
"""
Builds the player databases the game runs on: data.js (Cowboys) and
data-pit.js (Steelers). Team settings live in TEAMS below.

Sources (all free, from the nflverse project on GitHub):
  - rosters/roster_YYYY.csv  every NFL roster, 1960-today (all teams, so we
                             can tell which other teams a player played for)
  - players/players.csv      college and draft info
  - draft_picks/draft_picks.csv  draft info from 1980 on
  - stats_player/stats_player_week_YYYY.csv.gz  weekly stats from 1999 on

Downloads are cached in data/raw/ (gitignored). Re-run any time to refresh:
    python3 scripts/build_data.py            # all teams, uses cache
    python3 scripts/build_data.py pit        # just one team
    python3 scripts/build_data.py --refresh  # re-downloads the current season
"""

import csv
import gzip
import io
import json
import os
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
BASE = "https://github.com/nflverse/nflverse-data/releases/download"

FIRST_SEASON = 1960
LAST_SEASON = date.today().year if date.today().month >= 8 else date.today().year - 1
FIRST_STATS_SEASON = 1999

# Practice squad statuses don't count as playing for a team.
PRACTICE_SQUAD = {"DEV", "TRC"}

# Per-team settings. Each team builds its own data file.
TEAMS = {
    "DAL": {
        "out": "data.js",
        "super_bowls": [1971, 1977, 1992, 1993, 1995],  # seasons, not game years
        # Head coaches by season. 2010 counts for both Phillips and Garrett.
        "coaches": [
            ("Tom Landry", 1960, 1988),
            ("Jimmy Johnson", 1989, 1993),
            ("Barry Switzer", 1994, 1997),
            ("Chan Gailey", 1998, 1999),
            ("Dave Campo", 2000, 2002),
            ("Bill Parcells", 2003, 2006),
            ("Wade Phillips", 2007, 2010),
            ("Jason Garrett", 2010, 2019),
            ("Mike McCarthy", 2020, 2024),
            ("Brian Schottenheimer", 2025, 2099),
        ],
        # Pro Football Hall of Fame members who played for Dallas (through the 2026 class).
        "hall_of_fame": [
            "Bob Lilly", "Roger Staubach", "Tony Dorsett", "Randy White", "Mel Renfro",
            "Rayfield Wright", "Bob Hayes", "Troy Aikman", "Michael Irvin", "Emmitt Smith",
            "Larry Allen", "Deion Sanders", "Charles Haley", "Cliff Harris", "Chuck Howley",
            "Drew Pearson", "DeMarcus Ware", "Terrell Owens", "Lance Alworth", "Herb Adderley",
            "Forrest Gregg", "Mike Ditka", "Tommy McDonald", "Jackie Smith",
        ],
        # Ring of Honor players (coaches and executives left out).
        "team_honor": [
            "Bob Lilly", "Don Meredith", "Don Perkins", "Chuck Howley", "Mel Renfro",
            "Roger Staubach", "Lee Roy Jordan", "Tony Dorsett", "Randy White", "Bob Hayes",
            "Cliff Harris", "Rayfield Wright", "Troy Aikman", "Michael Irvin", "Emmitt Smith",
            "Drew Pearson", "Charles Haley", "Larry Allen", "Darren Woodson", "DeMarcus Ware",
        ],
        # Players who can appear as a row ("Played with ___"). Well-known names from
        # every era. Names must match nflverse spelling; the build warns on misses.
        "anchors": [
            # 1960s
            "Don Meredith", "Bob Lilly", "Don Perkins", "Chuck Howley", "Mel Renfro",
            "Bob Hayes", "Lee Roy Jordan", "Cornell Green", "Jethro Pugh", "Dan Reeves",
            "Craig Morton", "Ralph Neely", "Lance Rentzel",
            # 1970s
            "Roger Staubach", "Drew Pearson", "Tony Dorsett", "Randy White", "Cliff Harris",
            "Charlie Waters", "Rayfield Wright", "Too Tall Jones", "Harvey Martin", "Calvin Hill",
            "Preston Pearson", "Tony Hill", "Danny White", "Duane Thomas", "Walt Garrison",
            "Robert Newhouse", "Billy Joe DuPree", "Tom Henderson",
            # 1980s
            "Everson Walls", "Herschel Walker", "Jim Jeffcoat", "Doug Cosbie", "Eugene Lockhart",
            "Bill Bates", "Michael Downs", "Ron Springs",
            # 1990s
            "Troy Aikman", "Emmitt Smith", "Michael Irvin", "Jay Novacek", "Daryl Johnston",
            "Nate Newton", "Larry Allen", "Mark Stepnoski", "Erik Williams", "Charles Haley",
            "Russell Maryland", "Ken Norton", "Darren Woodson", "Deion Sanders", "Leon Lett",
            "Tony Tolbert", "Kevin Smith", "Alvin Harper",
            # 2000s
            "Jason Witten", "Tony Romo", "DeMarcus Ware", "Terrell Owens", "Terence Newman",
            "Marion Barber", "Flozell Adams", "La'Roi Glover", "Greg Ellis", "Dat Nguyen",
            "Keyshawn Johnson", "Drew Bledsoe", "Andre Gurode", "Bradie James", "Miles Austin",
            "Jay Ratliff", "Quincy Carter",
            # 2010s
            "Dez Bryant", "DeMarco Murray", "Sean Lee", "Tyron Smith", "Travis Frederick",
            "Zack Martin", "Ezekiel Elliott", "Dak Prescott", "Dan Bailey", "Orlando Scandrick",
            "Byron Jones", "Amari Cooper", "Jaylon Smith", "DeMarcus Lawrence",
            "Leighton Vander Esch", "La'el Collins", "Cole Beasley",
            # 2020s
            "CeeDee Lamb", "Micah Parsons", "Trevon Diggs", "Tony Pollard", "Dalton Schultz",
            "Brandon Aubrey", "Tyler Smith", "Jake Ferguson", "DaRon Bland", "Osa Odighizuwa",
            "Michael Gallup", "Tyler Biadasz",
        ],
        # Display-name fixes for nflverse spellings, and extra names people might type.
        "name_fixes": {"Demarcus Lawrence": "DeMarcus Lawrence"},
        "aliases": {
            "Too Tall Jones": ["Ed Jones", "Ed Too Tall Jones"],
            "Tom Henderson": ["Thomas Henderson", "Hollywood Henderson"],
            "Daryl Johnston": ["Moose Johnston"],
            "Bob Hayes": ["Bullet Bob Hayes"],
            "Ken Norton": ["Ken Norton Jr."],
            "Ezekiel Elliott": ["Zeke Elliott"],
            "Deion Sanders": ["Prime Time"],
        },
    },
    "PIT": {
        "out": "data-pit.js",
        "super_bowls": [1974, 1975, 1978, 1979, 2005, 2008],  # seasons, not game years
        "coaches": [
            ("Buddy Parker", 1960, 1964),
            ("Mike Nixon", 1965, 1965),
            ("Bill Austin", 1966, 1968),
            ("Chuck Noll", 1969, 1991),
            ("Bill Cowher", 1992, 2006),
            ("Mike Tomlin", 2007, 2025),
            ("Mike McCarthy", 2026, 2099),
        ],
        # Pro Football Hall of Fame players who were on a Steelers roster from 1960 on
        # (through the 2026 class).
        "hall_of_fame": [
            "Bobby Layne", "John Henry Johnson", "Ernie Stautner", "Terry Bradshaw",
            "Franco Harris", "Joe Greene", "Jack Lambert", "Jack Ham", "Mel Blount",
            "Mike Webster", "Lynn Swann", "John Stallworth", "Donnie Shell", "Rod Woodson",
            "Dermontti Dawson", "Kevin Greene", "Jerome Bettis", "Alan Faneca", "Troy Polamalu",
        ],
        # Steelers Hall of Honor players from 1960 on (coaches and executives left out),
        # through the 2026 class.
        "team_honor": [
            "Jerome Bettis", "Mel Blount", "Terry Bradshaw", "Dermontti Dawson", "Joe Greene",
            "Kevin Greene", "L.C. Greenwood", "Jack Ham", "Franco Harris", "Dick Hoak",
            "John Henry Johnson", "Jack Lambert", "Bobby Layne", "Andy Russell", "Donnie Shell",
            "John Stallworth", "Ernie Stautner", "Lynn Swann", "Mike Webster", "Rod Woodson",
            "Rocky Bleier", "Buddy Dial", "Alan Faneca", "Larry Brown", "Hines Ward",
            "James Farrior", "Greg Lloyd", "Troy Polamalu", "Mike Wagner", "Dwight White",
            "Tunch Ilkin", "Jon Kolb", "Carnell Lake", "Louis Lipps", "Sam Davis", "Heath Miller",
            "James Harrison", "Ray Mansfield", "Gerry Mullins", "Aaron Smith", "Jason Gildon",
            "Casey Hampton", "Willie Parker", "Joey Porter", "Maurkice Pouncey",
            "Ben Roethlisberger", "J.T. Thomas", "Craig Wolfley",
        ],
        "anchors": [
            # 1960s
            "Bobby Layne", "John Henry Johnson", "Ernie Stautner", "Andy Russell", "Buddy Dial",
            "Myron Pottios", "Dick Hoak", "Ray Mansfield", "Roy Jefferson", "Brady Keys",
            "Ben McGee",
            # 1970s
            "Terry Bradshaw", "Franco Harris", "Joe Greene", "Jack Lambert", "Jack Ham",
            "Mel Blount", "Mike Webster", "Lynn Swann", "John Stallworth", "L.C. Greenwood",
            "Dwight White", "Ernie Holmes", "Donnie Shell", "Rocky Bleier", "Mike Wagner",
            "J.T. Thomas", "Glen Edwards", "Larry Brown", "Jon Kolb", "Roy Gerela",
            # 1980s
            "Louis Lipps", "Mark Malone", "Gary Anderson", "Bryan Hinkle", "Mike Merriweather",
            "Rod Woodson", "Walter Abercrombie", "David Little", "Frank Pollard", "Bubby Brister",
            "Merril Hoge", "Tunch Ilkin",
            # 1990s
            "Neil O'Donnell", "Barry Foster", "Greg Lloyd", "Kevin Greene", "Dermontti Dawson",
            "Carnell Lake", "Levon Kirkland", "Jerome Bettis", "Kordell Stewart", "Yancey Thigpen",
            "Chad Brown", "Darren Perry", "Jason Gildon", "Hines Ward",
            # 2000s
            "Ben Roethlisberger", "Troy Polamalu", "Alan Faneca", "Joey Porter", "James Farrior",
            "Plaxico Burress", "Santonio Holmes", "Heath Miller", "Casey Hampton", "Aaron Smith",
            "James Harrison", "Ike Taylor", "Willie Parker", "Jeff Reed", "Tommy Maddox",
            # 2010s
            "Antonio Brown", "Le'Veon Bell", "LaMarr Woodley", "Lawrence Timmons", "Ryan Clark",
            "Maurkice Pouncey", "Cameron Heyward", "Ryan Shazier", "David DeCastro", "Brett Keisel",
            "Emmanuel Sanders", "Mike Wallace", "JuJu Smith-Schuster", "Stephon Tuitt",
            "Chris Boswell", "Bud Dupree", "T.J. Watt", "Rashard Mendenhall",
            # 2020s
            "Minkah Fitzpatrick", "Najee Harris", "Pat Freiermuth", "Diontae Johnson",
            "George Pickens", "Kenny Pickett", "Alex Highsmith", "Russell Wilson", "Justin Fields",
            "Jaylen Warren", "Aaron Rodgers", "DK Metcalf", "Joey Porter Jr.",
        ],
        "name_fixes": {"Ivan Taylor": "Ike Taylor"},
        "aliases": {
            "Joe Greene": ["Mean Joe Greene"],
            "Ben Roethlisberger": ["Big Ben"],
            "Jerome Bettis": ["The Bus"],
            "Joey Porter": ["Joey Porter Sr."],
            "L.C. Greenwood": ["LC Greenwood"],
            "J.T. Thomas": ["JT Thomas"],
            "T.J. Watt": ["TJ Watt"],
            "Ike Taylor": ["Ivan Taylor"],
        },
    },
}

# nflverse team codes -> today's franchise code, season-aware.
FIXED_CODES = {
    "ARZ": "ARI", "PHO": "ARI", "CHR": "ARI", "BLT": "BAL", "CLV": "CLE",
    "HST": "HOU", "SL": "LAR", "RAM": "LAR", "LA": "LAR", "RAI": "LV", "OAK": "LV",
    "SD": "LAC", "BOS": "NE", "NYT": "NYJ", "TEX": "KC", "COW": "DAL",
}


def franchise(code, season):
    if code == "STL":
        return "ARI" if season <= 1987 else "LAR"
    if code == "BAL":
        return "IND" if season <= 1983 else "BAL"
    if code == "HOU":
        return "TEN" if season <= 1996 else "HOU"
    return FIXED_CODES.get(code, code)


# ---------- downloading ----------

def fetch(rel_url, refresh=False):
    path = RAW / rel_url.replace("/", "__")
    if path.exists() and not refresh:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {rel_url}", file=sys.stderr)
    try:
        with urllib.request.urlopen(f"{BASE}/{rel_url}", timeout=60) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    path.write_bytes(data)
    return path


def read_csv(path):
    if path is None:
        return []
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ---------- identity: one id per real person ----------

class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def person_keys(gsis="", esb="", name="", dob=""):
    keys = []
    if gsis:
        keys.append("g:" + gsis)
    if esb:
        keys.append("g:" + esb)  # historical gsis ids in players.csv equal the esb id
    if name and dob:
        keys.append("nd:" + name.lower() + "|" + dob)
    return keys


def main():
    refresh = "--refresh" in sys.argv
    print(f"Seasons {FIRST_SEASON}-{LAST_SEASON}", file=sys.stderr)

    rosters = []
    for y in range(FIRST_SEASON, LAST_SEASON + 1):
        rows = read_csv(fetch(f"rosters/roster_{y}.csv", refresh and y == LAST_SEASON))
        for r in rows:
            r["_season"] = y
            r["_fr"] = franchise(r["team"], y)
        rosters.extend(rows)
    players_tbl = read_csv(fetch("players/players.csv", refresh))
    draft_tbl = read_csv(fetch("draft_picks/draft_picks.csv", refresh))
    stat_rows = {}
    for y in range(FIRST_STATS_SEASON, LAST_SEASON + 1):
        stat_rows[y] = [s for s in read_csv(fetch(f"stats_player/stats_player_week_{y}.csv.gz", refresh and y == LAST_SEASON))
                        if s.get("season_type") == "REG"]

    uf = UnionFind()
    row_key = []
    for i, r in enumerate(rosters):
        keys = person_keys(r.get("gsis_id", ""), r.get("esb_id", ""), r["full_name"], r.get("birth_date", ""))
        if not keys:  # no id and no birth date: treat as its own person
            keys = [f"row:{r['full_name'].lower()}|{r['team']}|{r['_season']}"]
        for k in keys[1:]:
            uf.union(keys[0], k)
        row_key.append(keys[0])
    for p in players_tbl:
        keys = person_keys(p["gsis_id"], p.get("esb_id", ""), p["display_name"], p.get("birth_date", ""))
        for k in keys[1:]:
            uf.union(keys[0], k)
        p["_key"] = keys[0] if keys else None
    for p in players_tbl:
        p["_id"] = uf.find(p["_key"]) if p["_key"] else None

    by_person = defaultdict(list)
    for i, r in enumerate(rosters):
        if r.get("status") in PRACTICE_SQUAD:
            continue
        by_person[uf.find(row_key[i])].append(r)

    info_by_person = {}
    for p in players_tbl:
        if p["_id"]:
            info_by_person.setdefault(p["_id"], p)
    draft_by_gsis = {d["gsis_id"]: d for d in draft_tbl if d["gsis_id"]}
    draft_by_pfr = {d["pfr_player_id"]: d for d in draft_tbl if d["pfr_player_id"]}

    teams = [t.upper() for t in sys.argv[1:] if not t.startswith("-")] or list(TEAMS)
    for team in teams:
        build_team(team, TEAMS[team], by_person, info_by_person, draft_by_gsis, draft_by_pfr, stat_rows)


def build_team(TEAM, cfg, by_person, info_by_person, draft_by_gsis, draft_by_pfr, stat_rows):
    print(f"Building {TEAM}", file=sys.stderr)
    # ---- weekly stats (1999+), this team's games only ----
    stat_seasons = defaultdict(lambda: defaultdict(Counter))  # gsis -> season -> totals
    games = defaultdict(int)
    for y, rows in stat_rows.items():
        for s in rows:
            if s.get("team") != TEAM:
                continue
            t = stat_seasons[s["player_id"]][y]
            for col in ("passing_yards", "rushing_yards", "receiving_yards", "def_sacks", "def_interceptions",
                        "passing_tds", "rushing_tds", "receiving_tds"):
                try:
                    t[col] += float(s.get(col) or 0)
                except ValueError:
                    pass
            games[s["player_id"]] += 1

    STAT_FLAGS = {
        "pass4000": ("passing_yards", 4000),
        "rush1000": ("rushing_yards", 1000),
        "rec1000": ("receiving_yards", 1000),
        "sack10": ("def_sacks", 10),
        "int5": ("def_interceptions", 5),
        "td10": (None, 10),  # rushing + receiving TDs
    }

    def pos_group(pos):
        pos = (pos or "").upper()
        if pos in ("QB",): return "QB"
        if pos in ("RB", "FB", "HB"): return "RB"
        if pos in ("WR",): return "WR"
        if pos in ("TE",): return "TE"
        if pos in ("OL", "T", "G", "C", "OT", "OG", "LS"): return "OL" if pos != "LS" else "ST"
        if pos in ("DL", "DE", "DT", "NT"): return "DL"
        if pos in ("LB", "OLB", "ILB", "MLB"): return "LB"
        if pos in ("DB", "CB", "S", "SS", "FS"): return "DB"
        if pos in ("K", "P", "SPEC"): return "ST"
        return None

    out_players = []
    for pid, rows in by_person.items():
        dal = [r for r in rows if r["_fr"] == TEAM]
        if not dal:
            continue
        dal.sort(key=lambda r: r["_season"])
        latest = dal[-1]
        info = info_by_person.get(pid) or {}
        gsis_ids = {r.get("gsis_id") for r in rows if r.get("gsis_id")}
        if info.get("gsis_id"):
            gsis_ids.add(info["gsis_id"])

        seasons = sorted({r["_season"] for r in dal})
        groups = Counter(g for g in (pos_group(r["position"]) for r in dal) if g)
        jerseys = sorted({int(n) for n in (r.get("jersey_number") or "" for r in dal) if n.isdigit() and int(n) > 0})
        others = sorted({r["_fr"] for r in rows if r["_fr"] != TEAM})

        college = next((r["college"] for r in reversed(dal) if r.get("college")), "") or info.get("college_name", "")
        draft = None  # None = unknown
        d = None
        for g in gsis_ids:
            d = d or draft_by_gsis.get(g)
        if not d and info.get("pfr_id"):
            d = draft_by_pfr.get(info["pfr_id"])
        if d:
            draft = {"y": int(d["season"]), "r": int(d["round"]), "p": int(d["pick"]), "t": franchise(d["team"], int(d["season"]))}
            college = college or d.get("college", "")
        elif info.get("draft_round"):
            dy = int(info["draft_year"] or 0)
            draft = {"y": dy, "r": int(float(info["draft_round"])), "p": int(float(info["draft_pick"] or 0)),
                     "t": franchise(info.get("draft_team") or "", dy)}
        else:
            first = int(info.get("rookie_season") or 0) or min(r["_season"] for r in rows)
            if first >= 1980 and info:  # draft records are complete from 1980 on
                draft = {"u": 1}

        flags = set()
        for g in gsis_ids:
            for y, t in stat_seasons.get(g, {}).items():
                for flag, (col, thresh) in STAT_FLAGS.items():
                    val = (t["rushing_tds"] + t["receiving_tds"]) if col is None else t[col]
                    if val >= thresh:
                        flags.add(flag)
        n_games = sum(games.get(g, 0) for g in gsis_ids)

        img = next((r["headshot_url"] for r in reversed(dal) if r.get("headshot_url")), "") or info.get("headshot", "")
        colleges = [c.strip() for c in college.split(";") if c.strip()]
        name = cfg["name_fixes"].get(latest["full_name"], latest["full_name"])
        out_players.append({
            "n": name,
            "b": (latest.get("birth_date") or info.get("birth_date") or "")[:4],
            "s": seasons,
            "g": groups.most_common(1)[0][0] if groups else "",
            "pg": sorted(groups),
            "j": jerseys,
            "c": colleges,
            "d": draft,
            "o": others,
            "fs": min(r["_season"] for r in rows),  # first season on any roster we have
            "f": sorted(flags),
            "gp": n_games,
            "img": img,
        })

    # Order: most seasons with the team first, then name, so autocomplete shows familiar players first.
    out_players.sort(key=lambda p: (-len(p["s"]), p["n"]))

    names = Counter(p["n"] for p in out_players)
    by_name = defaultdict(list)
    for i, p in enumerate(out_players):
        by_name[p["n"]].append(i)

    def lookup(name, label):
        idx = by_name.get(name, [])
        if not idx:
            print(f"  WARNING: {label} '{name}' not found", file=sys.stderr)
            return None
        return max(idx, key=lambda i: len(out_players[i]["s"]))  # the longest-tenured one

    for name in cfg["hall_of_fame"]:
        i = lookup(name, "Hall of Fame")
        if i is not None: out_players[i]["hof"] = 1
    for name in cfg["team_honor"]:
        i = lookup(name, "team honor")
        if i is not None: out_players[i]["roh"] = 1
    anchors = [i for i in (lookup(n, "anchor") for n in cfg["anchors"]) if i is not None]

    for name, alts in cfg["aliases"].items():
        i = lookup(name, "alias")
        if i is not None: out_players[i]["a"] = alts

    colleges = Counter(c for p in out_players for c in p["c"])
    top_colleges = sorted(c for c, n in colleges.items() if n >= 15)

    data = {
        "team": TEAM,
        "built": date.today().isoformat(),
        "seasons": [FIRST_SEASON, LAST_SEASON],
        "statsFrom": FIRST_STATS_SEASON,
        "superBowls": cfg["super_bowls"],
        "coaches": cfg["coaches"],
        "colleges": top_colleges,
        "anchors": anchors,
        "players": out_players,
    }
    js = "// Generated by scripts/build_data.py from nflverse data. Do not edit by hand.\n"
    js += "window.GRID_DATA = " + json.dumps(data, separators=(",", ":"), ensure_ascii=False) + ";\n"
    out = ROOT / cfg["out"]
    out.write_text(js, encoding="utf-8")

    dupes = [n for n, c in names.items() if c > 1]
    print(f"Wrote {out.name}: {len(out_players)} players, {len(anchors)} anchors, "
          f"{len(top_colleges)} colleges, {len(js)//1024} KB. {len(dupes)} shared names.", file=sys.stderr)


if __name__ == "__main__":
    main()
