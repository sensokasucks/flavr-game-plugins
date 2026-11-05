"""
Sumotori Dreams bets: who wins what when a round is settled, and how chat's side words are read.

Pure functions with no database or Core calls, so the tests can check the maths on their own.
plugin.py uses them from !bet (parse_side, parse_amount) and from settle_round() (payouts).

Two payout styles (``payout`` setting in plugin.json):
  pool    everyone's points go in one pot; the winning side shares it by stake (the classic Twitch
          prediction). If nobody backed one of the sides, everyone gets their points back.
  double  each winning bet gets twice its stake back; losing bets are gone. Points are created
          or lost against "the house", so this one can grow chat's points over time.
"""

from __future__ import annotations

from typing import Iterable, Optional

SIDES = ("a", "b")


def side_words(name_a: str, name_b: str) -> dict[str, str]:
    """Words chat may type for each side -> "a" / "b": the side names from settings (any case),
    plus a/b and 1/2 so a renamed side always has a fallback."""
    words = {"a": "a", "1": "a", "b": "b", "2": "b"}
    for side, name in (("a", name_a), ("b", name_b)):
        w = str(name or "").strip().lower()
        if w:
            words[w] = side
    return words


def parse_side(word: str, name_a: str, name_b: str) -> Optional[str]:
    """ "red" / "Red" / "1" / "a" -> "a" (when side A is called Red); None when it's neither side."""
    return side_words(name_a, name_b).get(str(word or "").strip().lower())


def parse_amount(word: str, balance: int) -> Optional[int]:
    """Bet size from chat: a whole number, "all" (the whole balance) or "half". None if unreadable.
    "1k" style shorthand is accepted (1k = 1000)."""
    w = str(word or "").strip().lower().replace(",", "")
    if w in ("all", "allin", "all-in", "max"):
        return int(balance)
    if w == "half":
        return int(balance) // 2
    mult = 1
    if w.endswith("k"):
        mult, w = 1000, w[:-1]
    try:
        val = float(w)
    except ValueError:
        return None
    if val != val or val <= 0:        # NaN or not positive
        return None
    return int(val * mult)


def payouts(bets: Iterable[dict], winner: str, style: str = "pool") -> tuple[dict[int, int], bool]:
    """Points to hand back for each bet row id when ``winner`` ("a" / "b") won.

    ``bets``: rows with "id", "side" and "amount". Returns ({bet id: points back}, refunded);
    bets that get nothing are left out. ``refunded`` is True when everyone got their stake back
    (pool style with one side empty). Pool shares are rounded down; the leftover points from
    rounding go to the biggest winning bet so the pot is always paid out in full.
    """
    rows = [dict(b) for b in bets if int(b.get("amount") or 0) > 0]
    if not rows:
        return {}, False
    winners = [b for b in rows if b["side"] == winner]
    if style == "double":
        return {int(b["id"]): int(b["amount"]) * 2 for b in winners}, False
    pot = sum(int(b["amount"]) for b in rows)
    won = sum(int(b["amount"]) for b in winners)
    if won == 0 or won == pot:        # nobody on one side: no contest, everyone gets their points back
        return {int(b["id"]): int(b["amount"]) for b in rows}, True
    out = {int(b["id"]): int(b["amount"]) * pot // won for b in winners}
    leftover = pot - sum(out.values())
    if leftover:
        top = max(winners, key=lambda b: (int(b["amount"]), -int(b["id"])))
        out[int(top["id"])] += leftover
    return out, False


def streak(winners: list[str]) -> tuple[Optional[str], int]:
    """Current run from a list of round winners, oldest first: ("a", 3) = side A won the last 3."""
    if not winners:
        return None, 0
    last = winners[-1]
    n = 0
    for w in reversed(winners):
        if w != last:
            break
        n += 1
    return last, n
