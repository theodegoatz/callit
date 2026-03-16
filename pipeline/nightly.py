# pipeline/nightly.py — Orchestrates the full pipeline (idempotent)
import sys
import traceback


def run_step(label, func, *args, **kwargs):
    print(f"\n{'─'*40}")
    print(f"▶ {label}")
    print(f"{'─'*40}")
    try:
        func(*args, **kwargs)
        print(f"✓ {label} complete")
        return True
    except Exception:
        traceback.print_exc()
        print(f"✗ {label} FAILED")
        return False


def main(season: int = 2024):
    from pipeline.ingest import main as ingest
    from pipeline.games import load_games
    from pipeline.extract import extract_decisions
    from pipeline.load_managers import load_managers
    from pipeline.manager import attribute_managers
    from pipeline.build_model import build_model
    from pipeline.score_all import score_all
    from pipeline.manager_grades import compute_grades
    from pipeline.validate import validate

    steps = [
        ("Ingest raw data", ingest),
        ("Load games", lambda: load_games(season)),
        ("Extract decision moments", lambda: extract_decisions(season)),
        ("Load managers", lambda: load_managers(season)),
        ("Attribute managers", lambda: attribute_managers(season)),
        ("Build model", lambda: build_model(season)),
        ("Score all decisions", lambda: score_all(season)),
        ("Compute manager grades", lambda: compute_grades(season)),
        ("Validate pipeline", lambda: validate(season)),
    ]

    results = []
    for label, func in steps:
        ok = run_step(label, func)
        results.append((label, ok))

    print(f"\n{'='*40}")
    print("Pipeline Summary")
    print(f"{'='*40}")
    for label, ok in results:
        status = "✓" if ok else "✗"
        print(f"  {status} {label}")

    all_ok = all(ok for _, ok in results)
    print(f"\nOverall: {'✓ ALL PASSED' if all_ok else '✗ SOME FAILED'}")

    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
