# pipeline/manager_grades.py — Computes manager grades from scored decisions
import pandas as pd
from sqlalchemy import text
from pipeline.db import get_engine


def compute_grades(season: int = 2024):
    engine = get_engine()

    with engine.connect() as conn:
        df = pd.read_sql(
            text(
                "SELECT manager_name, team, wpa_actual, wpa_optimal, "
                "       decision_value, is_optimal, is_ambiguous "
                "FROM decision_moments "
                "WHERE scored = TRUE AND manager_name IS NOT NULL "
                "AND game_id IN (SELECT game_id FROM games WHERE season = :s)"
            ),
            conn,
            params={"s": season},
        )

    if df.empty:
        print("[manager_grades] No scored decisions found.")
        return

    print(f"[manager_grades] Computing grades from {len(df)} scored decisions …")

    stats = df.groupby(["manager_name", "team"]).agg(
        total_decisions=("is_optimal", "count"),
        optimal_decisions=("is_optimal", "sum"),
        ambiguous_count=("is_ambiguous", "sum"),
        total_wpa=("wpa_actual", "sum"),
        avg_decision_val=("decision_value", "mean"),
    ).reset_index()

    stats["optimal_pct"] = stats["optimal_decisions"] / stats["total_decisions"]
    stats["score"] = (
        stats["optimal_pct"] * 60
        + stats["avg_decision_val"].clip(-0.05, 0.05).apply(lambda x: (x + 0.05) / 0.10 * 40)
    )
    stats["score"] = stats["score"].clip(0, 100).round(1)
    stats["grade"] = stats["score"].apply(_letter_grade)

    with engine.begin() as conn:
        for _, row in stats.iterrows():
            conn.execute(
                text(
                    "UPDATE managers SET "
                    "total_decisions = :td, "
                    "optimal_decisions = :od, "
                    "ambiguous_count = :ac, "
                    "total_wpa = :tw, "
                    "avg_decision_val = :adv, "
                    "grade = :grade, "
                    "score = :score "
                    "WHERE name = :name AND team = :team AND season = :s"
                ),
                {
                    "td": int(row["total_decisions"]),
                    "od": int(row["optimal_decisions"]),
                    "ac": int(row["ambiguous_count"]),
                    "tw": round(float(row["total_wpa"]), 5),
                    "adv": round(float(row["avg_decision_val"]), 5),
                    "grade": row["grade"],
                    "score": float(row["score"]),
                    "name": row["manager_name"],
                    "team": row["team"],
                    "s": season,
                },
            )

    print(f"[manager_grades] Updated grades for {len(stats)} managers")
    print("\n" + stats[["manager_name", "team", "total_decisions", "optimal_pct",
                         "score", "grade"]].to_string(index=False))


def _letter_grade(score):
    if score >= 93:
        return "A"
    elif score >= 85:
        return "A-"
    elif score >= 80:
        return "B+"
    elif score >= 73:
        return "B"
    elif score >= 65:
        return "B-"
    elif score >= 58:
        return "C+"
    elif score >= 50:
        return "C"
    elif score >= 40:
        return "D"
    else:
        return "F"


def main():
    compute_grades(2024)


if __name__ == "__main__":
    main()
