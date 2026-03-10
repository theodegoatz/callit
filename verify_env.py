#!/usr/bin/env python3
"""Quick check that the venv is active and all project deps import correctly."""
import sys

def main():
    in_venv = hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )
    if not in_venv:
        print("⚠️  Warning: venv may not be active. Run: source venv/bin/activate")
    else:
        print("✓ Virtual environment is active")

    packages = [
        "pybaseball",
        "pandas",
        "sqlalchemy",
        "psycopg2",
        "requests",
        "sklearn",
        "numpy",
        "dotenv",
        "supabase",
    ]
    failed = []
    for name in packages:
        try:
            __import__(name)
            print(f"  ✓ {name}")
        except ImportError as e:
            print(f"  ✗ {name}: {e}")
            failed.append(name)

    if failed:
        print(f"\nFailed: {failed}")
        sys.exit(1)
    print("\n✓ All packages OK. You're ready to go.")


if __name__ == "__main__":
    main()
