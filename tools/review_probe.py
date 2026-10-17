"""Throwaway file for testing the claude-review workflow; this PR is closed, never merged."""


def page_slice(items: list[str], page: int, size: int) -> list[str]:
    """Return 1-indexed page `page` of `items`, `size` items per page."""
    start = page * size
    return items[start : start + size]
