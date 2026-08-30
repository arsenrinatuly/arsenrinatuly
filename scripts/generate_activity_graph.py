#!/usr/bin/env python3
"""Generate monochrome SVG activity graphs from GitHub contribution data."""

from __future__ import annotations

import argparse
import html
import re
import urllib.parse
import urllib.request
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path


class ContributionParser(HTMLParser):
    """Extract contribution counts from GitHub's public calendar markup."""

    def __init__(self) -> None:
        super().__init__()
        self._cells: dict[str, date] = {}
        self._active_tooltip: str | None = None
        self.days: dict[date, int] = {}

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)

        if tag == "td":
            classes = (attributes.get("class") or "").split()
            cell_id = attributes.get("id")
            date_value = attributes.get("data-date")

            if "ContributionCalendar-day" in classes and cell_id and date_value:
                self._cells[cell_id] = date.fromisoformat(date_value)

        if tag == "tool-tip":
            cell_id = attributes.get("for")
            if cell_id in self._cells:
                self._active_tooltip = cell_id

    def handle_data(self, data: str) -> None:
        if self._active_tooltip is None:
            return

        count_match = re.search(r"(\d+)\s+contribution", data)
        count = int(count_match.group(1)) if count_match else 0
        self.days[self._cells[self._active_tooltip]] = count

    def handle_endtag(self, tag: str) -> None:
        if tag == "tool-tip":
            self._active_tooltip = None


def fetch_contributions(username: str) -> dict[date, int]:
    encoded_username = urllib.parse.quote(username, safe="")
    url = f"https://github.com/users/{encoded_username}/contributions"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "arsenrinatuly-profile-activity-graph/1.0",
        },
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        markup = response.read().decode("utf-8")

    parser = ContributionParser()
    parser.feed(markup)

    if len(parser.days) < 300:
        raise RuntimeError(
            f"GitHub returned only {len(parser.days)} contribution days; "
            "the calendar markup may have changed."
        )

    return parser.days


def select_recent_days(
    contributions: dict[date, int], number_of_days: int
) -> list[tuple[date, int]]:
    latest_available = max(contributions)
    end = min(date.today(), latest_available)
    start = end - timedelta(days=number_of_days - 1)

    return [
        (start + timedelta(days=offset), contributions.get(start + timedelta(days=offset), 0))
        for offset in range(number_of_days)
    ]


def render_svg(
    series: list[tuple[date, int]], username: str, *, dark: bool
) -> str:
    width = 1200
    height = 220
    left = 54
    right = 24
    top = 18
    bottom = 38
    chart_width = width - left - right
    chart_height = height - top - bottom

    colors = (
        {
            "background": "#0d1117",
            "grid": "#30363d",
            "text": "#8b949e",
            "line": "#f0f6fc",
            "point": "#ffffff",
            "area": "#6e7681",
        }
        if dark
        else {
            "background": "#ffffff",
            "grid": "#d0d7de",
            "text": "#57606a",
            "line": "#1f2328",
            "point": "#000000",
            "area": "#d0d7de",
        }
    )

    counts = [count for _, count in series]
    maximum = max(max(counts), 1)

    def x_position(index: int) -> float:
        return left + (chart_width * index / (len(series) - 1))

    def y_position(count: int) -> float:
        return top + chart_height - (chart_height * count / maximum)

    points = [(x_position(index), y_position(count)) for index, (_, count) in enumerate(series)]
    line_points = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    baseline = top + chart_height
    area_points = (
        f"{points[0][0]:.2f},{baseline:.2f} "
        f"{line_points} "
        f"{points[-1][0]:.2f},{baseline:.2f}"
    )

    horizontal_ticks = sorted({0, round(maximum / 2), maximum})
    label_indexes = list(range(0, len(series), 5))
    if label_indexes[-1] != len(series) - 1:
        label_indexes.append(len(series) - 1)

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        f"  <title>GitHub activity for {html.escape(username)} — last {len(series)} days</title>",
        "  <desc>Daily public contribution counts rendered as a monochrome line graph.</desc>",
        f'  <rect width="{width}" height="{height}" fill="{colors["background"]}" />',
        f'  <g fill="none" stroke="{colors["grid"]}" stroke-width="1">',
    ]

    for tick in horizontal_ticks:
        y = y_position(tick)
        parts.append(f'    <line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" />')

    for index in label_indexes:
        x = x_position(index)
        parts.append(f'    <line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{baseline}" opacity="0.45" />')

    parts.extend(
        [
            "  </g>",
            f'  <g fill="{colors["text"]}" font-family="ui-monospace, SFMono-Regular, Consolas, monospace" font-size="12">',
        ]
    )

    for tick in horizontal_ticks:
        y = y_position(tick) + 4
        parts.append(f'    <text x="{left - 12}" y="{y:.2f}" text-anchor="end">{tick}</text>')

    for index in label_indexes:
        x = x_position(index)
        label = series[index][0].strftime("%b %d")
        parts.append(f'    <text x="{x:.2f}" y="{height - 12}" text-anchor="middle">{label}</text>')

    parts.extend(
        [
            "  </g>",
            f'  <polygon points="{area_points}" fill="{colors["area"]}" opacity="0.28" />',
            f'  <polyline points="{line_points}" fill="none" stroke="{colors["line"]}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />',
            f'  <g fill="{colors["point"]}">',
        ]
    )

    for (x, y), count in zip(points, counts):
        if count > 0:
            radius = 4 if count == maximum else 3
            parts.append(f'    <circle cx="{x:.2f}" cy="{y:.2f}" r="{radius}" />')

    parts.extend(["  </g>", "</svg>", ""])
    return "\n".join(parts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--days", type=int, default=31)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.days < 7:
        raise ValueError("--days must be at least 7")

    contributions = fetch_contributions(args.username)
    series = select_recent_days(contributions, args.days)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    light_path = args.output_dir / "activity-graph.svg"
    dark_path = args.output_dir / "activity-graph-dark.svg"
    light_path.write_text(render_svg(series, args.username, dark=False), encoding="utf-8", newline="\n")
    dark_path.write_text(render_svg(series, args.username, dark=True), encoding="utf-8", newline="\n")

    total = sum(count for _, count in series)
    print(
        f"Generated {len(series)} days through {series[-1][0].isoformat()} "
        f"with {total} contributions."
    )


if __name__ == "__main__":
    main()
