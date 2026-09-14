"""
Computes solve statistics for the paid-tier stats dashboard: totals,
averages, favorite topics, difficulty breakdown, fastest solve, and solve
streaks.

Streak definition: a "streak" is a run of consecutive calendar days on
which the user completed at least one puzzle. The current streak counts
backward from today, but is still considered "alive" if the user
completed a puzzle yesterday and hasn't played yet today -- it doesn't
zero out at midnight before they've had a chance to keep it going.
"""
import datetime
from collections import Counter
from zoneinfo import ZoneInfo


def compute_streaks(solve_dates: set) -> tuple:
    """
    solve_dates: a set of distinct datetime.date values on which the user
    completed at least one puzzle.

    Returns (current_streak_days, longest_streak_days).
    """
    if not solve_dates:
        return 0, 0

    sorted_dates = sorted(solve_dates)

    longest = 1
    run = 1
    for i in range(1, len(sorted_dates)):
        if (sorted_dates[i] - sorted_dates[i - 1]).days == 1:
            run += 1
            longest = max(longest, run)
        else:
            run = 1

    # Central Time, not server-local (Render runs in UTC) -- same reasoning
    # as usage_limits.py and main.py's /on_this_day: a streak should break
    # or hold based on the same real-world "today" a US user actually
    # experiences, not UTC midnight (which would credit or break a streak
    # up to several hours off from the user's own day boundary).
    today = datetime.datetime.now(ZoneInfo("America/Chicago")).date()
    yesterday = today - datetime.timedelta(days=1)
    if today not in solve_dates and yesterday not in solve_dates:
        return 0, longest

    start = today if today in solve_dates else yesterday
    current = 0
    d = start
    while d in solve_dates:
        current += 1
        d -= datetime.timedelta(days=1)

    return current, longest


def build_stats(records: list) -> dict:
    """
    records: list of dicts, each with keys "topic", "difficulty",
    "solve_time_seconds", "hints_used", "completed", "logged_at" (a
    datetime.datetime). This is what SolveRecord rows get converted to
    before being passed here -- kept as plain dicts rather than taking
    SQLAlchemy model instances directly so this function has zero
    database dependency and can be tested completely offline.

    Returns the full stats payload for the dashboard.
    """
    total_attempted = len(records)
    completed_records = [r for r in records if r["completed"]]
    total_solved = len(completed_records)

    completion_rate = (total_solved / total_attempted) if total_attempted else 0.0

    avg_solve_time = (
        sum(r["solve_time_seconds"] for r in completed_records) / total_solved
        if total_solved else 0.0
    )
    avg_hints = (
        sum(r["hints_used"] for r in records) / total_attempted
        if total_attempted else 0.0
    )

    topic_counts = Counter(r["topic"] for r in records)
    favorite_topics = [
        {"topic": t, "times_played": c} for t, c in topic_counts.most_common(5)
    ]

    difficulty_counts = dict(Counter(r["difficulty"] for r in records))

    fastest = None
    if completed_records:
        fastest_record = min(completed_records, key=lambda r: r["solve_time_seconds"])
        fastest = {
            "topic": fastest_record["topic"],
            "solve_time_seconds": fastest_record["solve_time_seconds"],
        }

    solve_dates = {r["logged_at"].date() for r in completed_records}
    current_streak, longest_streak = compute_streaks(solve_dates)

    recent = sorted(records, key=lambda r: r["logged_at"], reverse=True)[:10]
    recent_activity = [
        {
            "topic": r["topic"],
            "difficulty": r["difficulty"],
            "solve_time_seconds": r["solve_time_seconds"],
            "hints_used": r["hints_used"],
            "completed": r["completed"],
            "logged_at": r["logged_at"].isoformat(),
        }
        for r in recent
    ]

    return {
        "total_solved": total_solved,
        "total_attempted": total_attempted,
        "completion_rate": round(completion_rate, 3),
        "average_solve_time_seconds": round(avg_solve_time, 1),
        "average_hints_used": round(avg_hints, 2),
        "favorite_topics": favorite_topics,
        "difficulty_breakdown": difficulty_counts,
        "fastest_solve": fastest,
        "current_streak_days": current_streak,
        "longest_streak_days": longest_streak,
        "recent_activity": recent_activity,
    }
