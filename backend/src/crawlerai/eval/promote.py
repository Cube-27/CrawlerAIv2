"""`crawlerai eval promote` and `crawlerai eval rotate-hidden` (SPEC-03 §4.4, ARCHITECTURE §16.1): move pages of the
private splits into dev. Fresh sites move after their one measured run; each quarter a share of the hidden sites
moves, and the custodian captures new ones to replace them.

A site moves whole: every page of a moved host goes to dev, so no host is in dev and in a private split at once, and
hidden stays "sites absent from dev" (§16.1). A page is moved by copying its bundle and row into the dev store and
then deleting the source row, in that order (§4.4), keeping its id and labels. The two stores are separate databases,
so a failure between the two steps leaves the page in both; running the command again finishes the move.

Nothing printed names a host or URL (C1): the report gives page and capture ids and counts.
"""

import json
import math
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from crawlerai.db.models import CaptureId, EvalCategory, EvalPageId
from crawlerai.eval.store import DevEvalStore, EvalNotFound, EvalPageRow, PrivateEvalStore


@dataclass(frozen=True)
class Moved:
    page_id: EvalPageId
    capture_id: CaptureId


@dataclass(frozen=True)
class Move:
    moved: tuple[Moved, ...]
    sites: int  # hosts moved
    kept: int  # pages left in the source split


async def promote(fresh: PrivateEvalStore, hidden: PrivateEvalStore, dev: DevEvalStore, all_pages: bool) -> Move:
    """Move each fresh site to dev whose pages are all `checked` (two passes, §16.2), or every fresh site with
    `all_pages`. A fresh site whose host also has hidden pages stays: moving it would put a hidden host in dev."""
    sites = await fresh.pages_by_host()
    hidden_hosts = (await hidden.pages_by_host()).keys()
    chosen = {
        host
        for host, pages in sites.items()
        if host not in hidden_hosts and (all_pages or all(page.labels.get("status") == "checked" for page in pages))
    }
    return await _move(fresh, dev, sites, chosen)


async def rotate_hidden(hidden: PrivateEvalStore, fresh: PrivateEvalStore, dev: DevEvalStore, fraction: float) -> Move:
    """Move `fraction` of the hidden sites to dev, chosen at random within each category (§16.1 stratifies hidden by
    category). A site's category is its first page's. A hidden site whose host also has fresh pages stays and is not
    counted in the fraction: moving it would put a fresh host in dev, and fresh is sites nobody has seen (§16.1)."""
    sites = await hidden.pages_by_host()
    fresh_hosts = (await fresh.pages_by_host()).keys()
    rotatable = {host: pages[0].category for host, pages in sites.items() if host not in fresh_hosts}
    chosen = choose_sites(rotatable, fraction)
    return await _move(hidden, dev, sites, chosen)


def check_fraction(fraction: float) -> float:
    if 0 < fraction < 1:  # NaN fails both comparisons and is refused
        return fraction
    raise ValueError("the fraction must be between 0 and 1, exclusive")


def choose_sites(categories: Mapping[str, EvalCategory], fraction: float, rng: random.Random | None = None) -> set[str]:
    """`fraction` of the hosts of each category, rounded half up, chosen uniformly at random."""
    check_fraction(fraction)
    rng = rng or random.SystemRandom()
    by_category: defaultdict[EvalCategory, list[str]] = defaultdict(list)
    for host, category in categories.items():
        by_category[category].append(host)
    chosen: set[str] = set()
    # Categories and hosts sorted, so a seeded `rng` chooses the same hosts whatever the order they were read in.
    for category in sorted(by_category):
        hosts = sorted(by_category[category])
        chosen.update(rng.sample(hosts, math.floor(fraction * len(hosts) + 0.5)))
    return chosen


async def _move(
    source: PrivateEvalStore, dev: DevEvalStore, sites: Mapping[str, Sequence[EvalPageRow]], chosen: set[str]
) -> Move:
    moved: list[Moved] = []
    for host in sorted(chosen):
        for page in sites[host]:
            await _move_page(source, dev, page)
            moved.append(Moved(page.id, page.capture_id))
    kept = sum(len(pages) for host, pages in sites.items() if host not in chosen)
    return Move(tuple(moved), len(chosen), kept)


async def _move_page(source: PrivateEvalStore, dev: DevEvalStore, page: EvalPageRow) -> None:
    bundle = await source.get_bundle(page.capture_id)
    await dev.put_capture(bundle, page.category)  # converges when the capture is already there
    try:
        await dev.get_page(page.id)  # copied by an interrupted run
    except EvalNotFound:
        await dev.put_page(page.model_copy(update={"split": "dev"}))
    await source.remove_page(page.id)


def report(move: Move) -> str:
    """One JSON line per moved page, then a line of counts."""
    lines: list[dict[str, object]] = [{"page_id": str(m.page_id), "capture_id": str(m.capture_id)} for m in move.moved]
    lines.append({"moved_pages": len(move.moved), "moved_sites": move.sites, "kept_pages": move.kept})
    return "".join(json.dumps(line) + "\n" for line in lines)
