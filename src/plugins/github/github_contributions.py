import requests
import logging
import calendar
from datetime import datetime, date, timedelta, timezone

logger = logging.getLogger(__name__)

# Sunday-first weekday labels, matching the calendar grid built below.
WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

GRAPHQL_QUERY = """
query($username: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $username) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
            date
          }
        }
      }
    }
  }
}
"""

def contributions_generate_image(plugin_instance, settings, device_config):
    dimensions = device_config.get_resolution()
    if device_config.get_config("orientation") == "vertical":
        dimensions = dimensions[::-1]

    api_key = device_config.load_env_key("GITHUB_SECRET")
    if not api_key:
        raise RuntimeError("GitHub API Key not configured.")

    colors = settings.get("contributionColor[]")
    github_username = settings.get("githubUsername")
    if not github_username:
        raise RuntimeError("GitHub username is required.")

    today = date.today()
    counts = fetch_contributions(github_username, api_key, today.year, today.month)
    weeks = build_month_grid(today.year, today.month, counts, colors, today)
    metrics = calculate_metrics(counts, today.year, today.month, today)

    template_params = {
        "username": github_username,
        "weeks": weeks,
        "weekday_labels": WEEKDAY_LABELS,
        "month_label": date(today.year, today.month, 1).strftime("%B %Y"),
        "metrics": metrics,
        "plugin_settings": settings
    }

    return plugin_instance.render_image(
        dimensions,
        "github_contributions.html",
        "github.css",
        template_params
    )

# -------------------------
# Helper functions
# -------------------------

def fetch_contributions(username, api_key, year, month):
    """Fetch the contribution counts for a single month, keyed by ISO date."""
    last_day = calendar.monthrange(year, month)[1]
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    # The GitHub API rejects a `to` in the future, so clamp to now.
    now = datetime.now(timezone.utc)
    if end > now:
        end = now

    url = "https://api.github.com/graphql"
    headers = {"Authorization": f"Bearer {api_key}"}
    variables = {
        "username": username,
        "from": start.isoformat(),
        "to": end.isoformat(),
    }
    resp = requests.post(url, json={"query": GRAPHQL_QUERY, "variables": variables}, headers=headers, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("errors"):
        raise RuntimeError(f"GitHub API error: {payload['errors']}")

    weeks = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    counts = {}
    for week in weeks:
        for day in week["contributionDays"]:
            counts[day["date"]] = day["contributionCount"]
    return counts

def build_month_grid(year, month, counts, colors, today):
    """Build a Sunday-first calendar grid (weeks of day cells) for the month."""
    in_month_counts = [
        count for iso, count in counts.items()
        if iso.startswith(f"{year:04d}-{month:02d}-")
    ]
    max_contrib = max(in_month_counts) if in_month_counts else 0

    def get_color(count):
        if max_contrib == 0 or count == 0:
            return colors[0]
        level = int((count / max_contrib) * (len(colors) - 1))
        return colors[max(1, level)]

    cal = calendar.Calendar(firstweekday=6)  # 6 = Sunday
    weeks = []
    for week in cal.monthdatescalendar(year, month):
        row = []
        for d in week:
            in_month = d.month == month
            is_future = d > today
            count = counts.get(d.isoformat(), 0)
            row.append({
                "date": d.isoformat(),
                "day": d.day,
                "count": count,
                "color": get_color(count),
                "in_month": in_month,
                "is_future": is_future,
            })
        weeks.append(row)
    return weeks

def calculate_metrics(counts, year, month, today):
    prefix = f"{year:04d}-{month:02d}-"
    days = sorted((iso, count) for iso, count in counts.items() if iso.startswith(prefix))

    total = sum(count for _, count in days)
    streak, longest_streak, current_streak = 0, 0, 0
    yesterday = today - timedelta(days=1)
    in_current_streak = False

    for iso, count in days:
        day_date = date.fromisoformat(iso)
        if count > 0:
            streak += 1
            longest_streak = max(longest_streak, streak)
            if day_date in (today, yesterday) or in_current_streak:
                current_streak = streak
                in_current_streak = True
        else:
            streak = 0
            in_current_streak = False

    return [
        {"title": "Contributions", "value": total},
        {"title": "Current Streak", "value": current_streak},
        {"title": "Longest Streak", "value": longest_streak},
    ]
