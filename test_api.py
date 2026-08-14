import sys

from src.api.sleeper import get_draft_status, get_draft_picks

if len(sys.argv) < 2:
    print("Usage: python test_api.py <draft_id>")
    sys.exit(1)

draft_id = sys.argv[1]

print(f"Fetching draft status for draft_id={draft_id}...")
status = get_draft_status(draft_id)
print(status)

print(f"\nFetching draft picks for draft_id={draft_id}...")
picks = get_draft_picks(draft_id)
print(picks)
