# pipeline/validate.py — Prints accuracy and quality metrics
import pandas as pd
from sqlalchemy import text
from pipeline.db import get_engine


def validate(season: int = 2024):
    engine = get_engine()

    with engine.connect() as conn:
        n_games = conn.execute(
            text("SELECT COUNT(*) FROM games WHERE season = :s"), {"s": season}
        ).scalar()

        n_decisions = conn.execute(
            text(
                "SELECT COUNT(*) FROM decision_moments "
                "WHERE game_id IN (SELECT game_id FROM games WHERE season = :s)"
            ),
            {"s": season},
        ).scalar()

        n_scored = conn.execute(
            text(
                "SELECT COUNT(*) FROM decision_moments "
                "WHERE scored = TRUE "
                "AND game_id IN (SELECT game_id FROM games WHERE season = :s)"
            ),
            {"s": season},
        ).scalar()

        n_managers = conn.execute(
            text("SELECT COUNT(*) FROM managers WHERE season = :s"), {"s": season}
        ).scalar()

        n_graded = conn.execute(
            text("SELECT COUNT(*) FROM managers WHERE season = :s AND grade IS NOT NULL"),
            {"s": season},
        ).scalar()

        stats = pd.read_sql(
            text(
                "SELECT is_optimal, is_ambiguous, decision_value "
                "FROM decision_moments "
                "WHERE scored = TRUE "
                "AND game_id IN (SELECT game_id FROM games WHERE season = :s)"
            ),
            conn,
            params={"s": season},
        )

    print(f"\n{'='*50}")
    print(f"  CallIt Pipeline Validation — Season {season}")
    print(f"{'='*50}")
    print(f"  Games loaded:          {n_games:>6}")
    print(f"  Decision moments:      {n_decisions:>6}")
    print(f"  Scored decisions:      {n_scored:>6}")
    print(f"  Managers loaded:       {n_managers:>6}")
    print(f"  Managers graded:       {n_graded:>6}")

    if not stats.empty:
        n_ambiguous = int(stats["is_ambiguous"].sum())
        scored = len(stats)
        dv = stats["decision_value"]
        n_clear_optimal = int((dv >= 0.02).sum())
        n_clear_suboptimal = int((dv < -0.02).sum())
        non_ambiguous = n_clear_optimal + n_clear_suboptimal
        n_optimal_total = int(stats["is_optimal"].sum())
        optimal_pct = n_optimal_total / scored * 100 if scored else 0
        clear_accuracy = n_clear_optimal / non_ambiguous * 100 if non_ambiguous else 0
        avg_dv = dv.mean()

        print(f"\n  --- Scoring Metrics ---")
        print(f"  Optimal decisions:     {n_optimal_total:>6} ({optimal_pct:.1f}%)")
        print(f"  Ambiguous (|dv|<0.02): {n_ambiguous:>6} ({n_ambiguous/scored*100:.1f}%)")
        print(f"  Clear-call accuracy:   {clear_accuracy:.1f}%")
        print(f"  Avg decision value:    {avg_dv:>+.5f}")

    scoring_coverage = n_scored / n_decisions * 100 if n_decisions else 0
    grading_coverage = n_graded / n_managers * 100 if n_managers else 0
    print(f"\n  --- Coverage ---")
    print(f"  Scoring coverage:      {scoring_coverage:.1f}%")
    print(f"  Grading coverage:      {grading_coverage:.1f}%")

    ok = n_games > 0 and n_scored > 0 and n_graded > 0
    print(f"\n  Overall: {'✓ PASS' if ok else '✗ FAIL'}")
    print(f"{'='*50}\n")

    return ok


def main():
    validate(2024)


if __name__ == "__main__":
    main()
