# pipeline/load_managers.py — Loads manager-team assignments for a season
from sqlalchemy import text
from pipeline.db import get_engine

MANAGERS_2024 = {
    "NYY": "Aaron Boone",
    "BOS": "Alex Cora",
    "TBR": "Kevin Cash",
    "TOR": "John Schneider",
    "BAL": "Brandon Hyde",
    "CLE": "Stephen Vogt",
    "MIN": "Rocco Baldelli",
    "DET": "A.J. Hinch",
    "CHW": "Pedro Grifol",
    "KCR": "Matt Quatraro",
    "HOU": "Joe Espada",
    "SEA": "Scott Servais",
    "TEX": "Bruce Bochy",
    "LAA": "Ron Washington",
    "OAK": "Mark Kotsay",
    "ATL": "Brian Snitker",
    "NYM": "Carlos Mendoza",
    "PHI": "Rob Thomson",
    "MIA": "Skip Schumaker",
    "WSN": "Dave Martinez",
    "MIL": "Pat Murphy",
    "CHC": "Craig Counsell",
    "STL": "Oli Marmol",
    "CIN": "David Bell",
    "PIT": "Derek Shelton",
    "LAD": "Dave Roberts",
    "SDP": "Mike Shildt",
    "SFG": "Bob Melvin",
    "ARI": "Torey Lovullo",
    "COL": "Bud Black",
}


def load_managers(season: int = 2024):
    engine = get_engine()
    mapping = MANAGERS_2024 if season == 2024 else MANAGERS_2024

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM managers WHERE season = :s"), {"s": season})
        for team, name in mapping.items():
            conn.execute(
                text(
                    "INSERT INTO managers (name, team, season) "
                    "VALUES (:name, :team, :season) "
                    "ON CONFLICT (name, team, season) DO NOTHING"
                ),
                {"name": name, "team": team, "season": season},
            )

    print(f"[load_managers] Loaded {len(mapping)} managers for {season}")


def main():
    load_managers(2024)


if __name__ == "__main__":
    main()
