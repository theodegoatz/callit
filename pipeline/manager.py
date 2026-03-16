# pipeline/manager.py — Attributes decisions to managers
import pandas as pd
from sqlalchemy import text
from pipeline.db import get_engine


def attribute_managers(season: int = 2024):
    """Assign manager_name to each decision moment based on team + season."""
    engine = get_engine()

    with engine.connect() as conn:
        managers = pd.read_sql(
            text("SELECT name, team FROM managers WHERE season = :s"),
            conn,
            params={"s": season},
        )

    if managers.empty:
        print("[manager] No managers loaded. Run pipeline/load_managers.py first.")
        return

    team_to_mgr = dict(zip(managers["team"], managers["name"]))

    with engine.begin() as conn:
        for team, mgr in team_to_mgr.items():
            conn.execute(
                text(
                    "UPDATE decision_moments SET manager_name = :mgr "
                    "WHERE team = :team AND manager_name IS NULL "
                    "AND game_id IN (SELECT game_id FROM games WHERE season = :s)"
                ),
                {"mgr": mgr, "team": team, "s": season},
            )

    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM decision_moments "
                "WHERE manager_name IS NOT NULL "
                "AND game_id IN (SELECT game_id FROM games WHERE season = :s)"
            ),
            {"s": season},
        )
        count = result.scalar()

    print(f"[manager] Attributed {count} decisions to managers for {season}")


def main():
    attribute_managers(2024)


if __name__ == "__main__":
    main()
