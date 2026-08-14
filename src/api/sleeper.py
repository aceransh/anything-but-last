import requests

BASE_URL = "https://api.sleeper.app/v1"


def get_draft_status(draft_id: str) -> dict:
    url = f"{BASE_URL}/draft/{draft_id}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching draft status for draft_id={draft_id}: {e}")
        return {}


def get_draft_picks(draft_id: str) -> list:
    url = f"{BASE_URL}/draft/{draft_id}/picks"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching draft picks for draft_id={draft_id}: {e}")
        return []
