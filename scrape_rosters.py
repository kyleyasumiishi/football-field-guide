"""
scrape_rosters.py
-----------------
Fetches NFL depth chart starters from the ESPN API for all 32 teams
and outputs rosters.json — a file you paste into index.html.

Uses two ESPN endpoints per team:
  1. Roster endpoint  → builds an athlete ID → full name lookup
  2. Depth chart endpoint → ranked starters (rank 1 = starter) per position

This two-step approach is necessary because the roster endpoint returns
players in alphabetical order, while the depth chart endpoint returns
them in true depth-chart order (starter first).

Usage:
    python3 scrape_rosters.py              # scrape all 32 teams
    python3 scrape_rosters.py SEA DAL SF   # scrape specific teams (by abbr)

Output:
    rosters.json

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW TO UPDATE ROSTERS FOR A NEW SEASON (e.g. 2026-2027)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP 1 — Wait for rosters to stabilize
    Run this after final cuts (typically the Tuesday after the last
    preseason game, around late August). ESPN's depth chart reflects
    the active 53-man roster, so running it too early may return
    preseason depth charts that don't reflect final decisions.

STEP 2 — Run the script
    python3 scrape_rosters.py

    This overwrites rosters.json with fresh data for all 32 teams.
    To update just a few teams (e.g. after a trade):
    python3 scrape_rosters.py SEA PHI KC

STEP 3 — Paste the new data into index.html
    Open the freshly written rosters.json. Copy its entire contents.
    In index.html, find the line that starts:
        const ROSTERS = {
    Replace everything from that line up to (and including) the
    closing };  with:
        const ROSTERS = <paste here>;

    Claude can do this step automatically — just say:
    "Update the ROSTERS constant in index.html using rosters.json"

STEP 4 — Verify
    Open index.html in a browser, select any team from the Off./Def.
    Roster dropdowns, and spot-check a few player names against the
    official team website or ESPN's depth chart page.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW THIS SCRIPT WORKS (for Claude context)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Calls ESPN's teams list endpoint to discover all 32 team IDs
   dynamically — no hardcoded IDs, so it works across seasons.

2. For each team, fetches TWO endpoints:
   a. Roster:
      https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{id}/roster
      Used only to build an athlete_id → fullName lookup dict.
      (The roster endpoint returns players alphabetically, not by
      depth chart order — this is why we need the second endpoint.)

   b. Depth chart:
      https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/{year}/teams/{id}/depthcharts
      Returns formations (e.g. "3WR 1TE", "Base 4-3 D") each with
      positions and ranked athletes. rank=1 is the starter.
      Athlete references are IDs only ($ref URLs), so we resolve
      names using the lookup built in step (a).

3. SEASON YEAR: The depth chart URL includes the season year (e.g. 2025).
   Update SEASON below at the start of each new season.

4. FORMATION SELECTION:
   - Offense: the formation whose positions include 'qb'
   - Defense: the formation whose positions include 'mlb' or 'lilb'
     (3-4 teams use 'lilb' for the left inside linebacker instead of 'mlb')

5. POSITION MAPPING (see OFFENSE_DEPTH_MAP / DEFENSE_DEPTH_MAP below):
   ESPN depth chart uses short position keys like 'lt', 'wr', 'lde'.
   These map to the app's internal position IDs.
   - 4-3 defense uses: lde, ldt, rdt, rde, mlb, wlb, slb
   - 3-4 defense uses: lde, nt, rde, lilb, rilb, wlb, slb
   Both are handled by the same map; first filled slot wins.

TROUBLESHOOTING:
   - Wrong starters → ESPN may have a different formation name. Print
     [item['name'] for item in depth_chart['items']] for that team and
     check which formation contains the expected position keys.
   - Empty positions → ESPN may have renamed a position key. Print
     item['positions'].keys() for the relevant formation and update
     OFFENSE_DEPTH_MAP / DEFENSE_DEPTH_MAP.
   - HTTP 429 / rate limit → increase DELAY (currently 1 second).
   - "Season not found" errors → update SEASON to the current year.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
import re
import json
import time
import requests

# ─── CONFIG ───────────────────────────────────────────────────────────────────
# Update SEASON at the start of each new NFL season year.
# 2025 = the 2025-2026 season. Change to 2026 for the 2026-2027 season, etc.
SEASON = 2025

DELAY = 1  # seconds between teams — be polite to ESPN

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

TEAMS_URL    = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams?limit=32"
ROSTER_URL   = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team_id}/roster"
DEPTHCHART_URL = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/{season}/teams/{team_id}/depthcharts"


# ─── POSITION MAPPING ─────────────────────────────────────────────────────────
# Maps ESPN depth chart position keys → app position IDs.
# For positions with multiple slots (WR → WR1/WR2/WR3), athletes are assigned
# in rank order (rank 1 → first slot, rank 2 → second slot, etc.).
# First filled slot wins — so 4-3 and 3-4 keys coexist safely.

OFFENSE_DEPTH_MAP = {
    # Key: ESPN depth chart position key → list of app IDs to fill in order
    "qb":  ["QB"],
    "lt":  ["LT"],
    "lg":  ["LG"],
    "c":   ["C"],
    "rg":  ["RG"],
    "rt":  ["RT"],
    "wr":  ["WR1", "WR2", "WR3"],  # up to 3 WRs by rank
    "te":  ["TE"],
    "rb":  ["RB"],
    "fb":  ["FB"],
}

DEFENSE_DEPTH_MAP = {
    # 4-3 and 3-4 keys handled together
    "lde":  ["DE1"],
    "rde":  ["DE2"],
    "ldt":  ["DT1"],          # 4-3 left DT
    "rdt":  ["DT2"],          # 4-3 right DT
    "nt":   ["DT1"],          # 3-4 nose tackle → DT1 slot
    "mlb":  ["MLB"],          # 4-3 middle LB
    "lilb": ["MLB"],          # 3-4 left inside LB → MLB slot
    "rilb": ["WILL"],         # 3-4 right inside LB → WILL slot
    "wlb":  ["WILL"],         # 4-3 weak-side OLB → WILL slot
    "slb":  ["SAM"],          # strong-side OLB
    "lcb":  ["LCB"],
    "rcb":  ["RCB"],
    "ss":   ["SS"],
    "fs":   ["FS"],
}


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def fetch_json(url):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def athlete_id_from_ref(ref_url):
    """Extract numeric athlete ID from an ESPN $ref URL."""
    m = re.search(r"/athletes/(\d+)", ref_url)
    return m.group(1) if m else None


def get_all_teams():
    """Return list of { id, abbr, name } for all 32 NFL teams."""
    data = fetch_json(TEAMS_URL)
    teams = []
    for item in data["sports"][0]["leagues"][0]["teams"]:
        t = item["team"]
        teams.append({
            "id":   t["id"],
            "abbr": t["abbreviation"].upper(),
            "name": t["displayName"],
        })
    return teams


def build_id_name_map(team_id):
    """Fetch the roster and return { athlete_id_str: fullName }."""
    data = fetch_json(ROSTER_URL.format(team_id=team_id))
    return {
        str(player["id"]): player["fullName"]
        for group in data.get("athletes", [])
        for player in group.get("items", [])
    }


def extract_positions(formation, id_to_name, position_map):
    """
    Given a depth chart formation dict, extract starters mapped to app IDs.
    Returns { app_position_id: "Player Full Name" }.
    """
    result = {}
    filled = set()

    for depth_key, app_ids in position_map.items():
        pos_data = formation["positions"].get(depth_key, {})
        athletes = sorted(pos_data.get("athletes", []), key=lambda a: a["rank"])
        slot_index = 0
        for athlete_entry in athletes:
            if slot_index >= len(app_ids):
                break
            app_id = app_ids[slot_index]
            if app_id in filled:
                slot_index += 1
                continue
            ref = athlete_entry["athlete"].get("$ref", "")
            athlete_id = athlete_id_from_ref(ref)
            if athlete_id and athlete_id in id_to_name:
                result[app_id] = id_to_name[athlete_id]
                filled.add(app_id)
            slot_index += 1

    return result


def scrape_team(team_id):
    """Return { offense: {...}, defense: {...} } for one team."""
    # Step 1: build athlete ID → name lookup from roster endpoint
    id_to_name = build_id_name_map(team_id)

    # Step 2: fetch depth chart
    dc_data = fetch_json(DEPTHCHART_URL.format(season=SEASON, team_id=team_id))
    formations = dc_data.get("items", [])

    # Step 3: find the base offense formation (has 'qb' position)
    off_formation = next(
        (f for f in formations if "qb" in f.get("positions", {})),
        None
    )

    # Step 4: find the base defense formation (has 'mlb' or 'lilb' position)
    def_formation = next(
        (f for f in formations if "mlb" in f.get("positions", {}) or "lilb" in f.get("positions", {})),
        None
    )

    offense = extract_positions(off_formation, id_to_name, OFFENSE_DEPTH_MAP) if off_formation else {}
    defense = extract_positions(def_formation, id_to_name, DEFENSE_DEPTH_MAP) if def_formation else {}

    if len(offense) < 5:
        print(f"    ⚠️  Only {len(offense)} offense positions — check formation names: {[f['name'] for f in formations]}")
    if len(defense) < 5:
        print(f"    ⚠️  Only {len(defense)} defense positions — check formation names: {[f['name'] for f in formations]}")

    return {"offense": offense, "defense": defense}


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("Fetching team list from ESPN...")
    all_teams = get_all_teams()
    team_by_abbr = {t["abbr"]: t for t in all_teams}

    if len(sys.argv) > 1:
        requested = [a.upper() for a in sys.argv[1:]]
        invalid = [a for a in requested if a not in team_by_abbr]
        if invalid:
            print(f"Unknown team abbreviations: {invalid}")
            print(f"Valid abbreviations: {sorted(team_by_abbr.keys())}")
            sys.exit(1)
        target_teams = [team_by_abbr[a] for a in requested]
    else:
        target_teams = sorted(all_teams, key=lambda t: t["name"])

    print(f"Scraping {len(target_teams)} team(s) — using {SEASON} depth charts...\n")

    rosters = {}

    for i, team in enumerate(target_teams):
        abbr = team["abbr"]
        name = team["name"]
        print(f"[{i+1}/{len(target_teams)}] {name} ({abbr})")

        try:
            data = scrape_team(team["id"])
            rosters[abbr] = {
                "name":    name,
                "offense": data["offense"],
                "defense": data["defense"],
            }
            print(f"    ✓ {len(data['offense'])} offense, {len(data['defense'])} defense positions")
        except Exception as e:
            print(f"    ❌ Failed: {e}")
            rosters[abbr] = {
                "name":    name,
                "offense": {},
                "defense": {},
                "error":   str(e),
            }

        if i < len(target_teams) - 1:
            time.sleep(DELAY)

    output_path = "rosters.json"
    with open(output_path, "w") as f:
        json.dump(rosters, f, indent=2)

    print(f"\n✅ Done. Wrote {len(rosters)} teams to {output_path}")


if __name__ == "__main__":
    main()
