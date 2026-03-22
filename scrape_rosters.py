"""
scrape_rosters.py
-----------------
Fetches NFL rosters from the ESPN unofficial API for all 32 teams
and outputs rosters.json — a file you paste into index.html.

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
    preseason game, around late August). ESPN's API reflects the
    active 53-man roster, so running it too early will pull preseason
    rosters that don't reflect final depth charts.

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
   dynamically — no hardcoded IDs, so it works across seasons even
   if ESPN renumbers teams.

2. For each team, fetches:
   https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{id}/roster
   No API key required. ESPN makes this endpoint public.

3. The response groups players by "offense", "defense", etc.
   Each player has fullName and position.abbreviation.

4. POSITION MAPPING (see OFFENSE_MAP / DEFENSE_MAP below):
   ESPN doesn't distinguish left vs. right for tackles (OT) or
   guards (G), so the script assigns LT/RT and LG/RG by order of
   appearance on the roster. If ESPN changes position abbreviations
   in a future season, add the new abbreviation to the relevant map.

5. Outputs rosters.json keyed by team abbreviation (e.g. "SEA"),
   with "offense" and "defense" sub-objects keyed by the app's
   internal position IDs (QB, LT, LG, C, RG, RT, WR1-3, TE, RB, FB
   for offense; DE1, DE2, DT1, DT2, MLB, WILL, SAM, LCB, RCB, FS,
   SS for defense).

TROUBLESHOOTING:
   - "Only N offense positions found" warning → ESPN may have changed
     position abbreviations. Print the raw ESPN positions for that
     team and update OFFENSE_MAP / DEFENSE_MAP accordingly.
   - HTTP 429 / rate limit → increase DELAY (currently 1 second).
   - A team returns an empty roster → ESPN may have changed the
     response structure. Print raw data for that team_id and update
     the fetch_json / scrape_team parsing logic.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
import json
import time
import requests

DELAY = 1  # seconds between requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams?limit=32"
ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team_id}/roster"

# ─── POSITION MAPPING ─────────────────────────────────────────────────────────
# Maps ESPN position abbreviations → app position IDs (in priority order).
# The first unfilled slot in the list gets the next player of that ESPN position.

OFFENSE_MAP = {
    "QB":  ["QB"],
    "C":   ["C"],
    "OT":  ["LT", "RT"],     # ESPN doesn't distinguish L/R — assign by order
    "OG":  ["LG", "RG"],     # offensive guard
    "G":   ["LG", "RG"],
    "T":   ["LT", "RT"],
    "WR":  ["WR1", "WR2", "WR3"],
    "TE":  ["TE"],
    "RB":  ["RB"],
    "FB":  ["FB"],
    "HB":  ["RB"],
    "OL":  ["LT", "LG", "C", "RG", "RT"],  # generic OL
}

DEFENSE_MAP = {
    "DE":  ["DE1", "DE2"],
    "DT":  ["DT1", "DT2"],
    "NT":  ["DT1", "DT2"],
    "DL":  ["DE1", "DT1", "DT2", "DE2"],
    "MLB": ["MLB"],
    "ILB": ["MLB", "WILL"],
    "OLB": ["SAM", "WILL"],
    "LB":  ["MLB", "WILL", "SAM"],
    "CB":  ["LCB", "RCB"],
    "FS":  ["FS"],
    "SS":  ["SS"],
    "S":   ["SS", "FS"],
    "DB":  ["LCB", "RCB"],
}


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def fetch_json(url):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_all_teams():
    """Return list of { id, abbr, name } for all 32 NFL teams."""
    data = fetch_json(TEAMS_URL)
    teams = []
    for item in data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
        t = item.get("team", {})
        teams.append({
            "id":   t["id"],
            "abbr": t["abbreviation"].upper(),
            "name": t["displayName"],
        })
    return teams


def map_positions(items, position_map):
    """
    Given a list of ESPN player items and a position map,
    return { app_id: "Player Name" } for starters.
    Each app slot is filled at most once (first player wins).
    """
    result = {}
    used = set()

    for player in items:
        espn_pos = player.get("position", {}).get("abbreviation", "").upper()
        if espn_pos not in position_map:
            continue
        for app_id in position_map[espn_pos]:
            if app_id not in used:
                result[app_id] = player.get("fullName", "")
                used.add(app_id)
                break  # only consume one slot per player

    return result


def scrape_team(team_id):
    """Fetch ESPN roster for team_id, return { offense: {...}, defense: {...} }."""
    data = fetch_json(ROSTER_URL.format(team_id=team_id))

    offense_players = []
    defense_players = []

    for group in data.get("athletes", []):
        group_pos = group.get("position", "").lower()
        items = group.get("items", [])
        if group_pos == "offense":
            offense_players.extend(items)
        elif group_pos == "defense":
            defense_players.extend(items)

    offense = map_positions(offense_players, OFFENSE_MAP)
    defense = map_positions(defense_players, DEFENSE_MAP)

    if len(offense) < 3:
        print(f"    ⚠️  Only {len(offense)} offense positions found — ESPN structure may have changed")

    return {"offense": offense, "defense": defense}


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("Fetching team list from ESPN...")
    all_teams = get_all_teams()
    team_by_abbr = {t["abbr"]: t for t in all_teams}

    # Optional: filter to specific teams via CLI args (e.g. SEA DAL SF)
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

    print(f"Scraping {len(target_teams)} team(s)...\n")

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
