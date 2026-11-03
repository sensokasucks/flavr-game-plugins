"""
Chat names a new mix: the vote behind the "Let chat name it" button on Schedule I's naming screen.

When the streamer makes a new mix at a mixing station, the game opens its naming screen. The
FridgeSchedule1 mod (fridge-schedule1/mod/MixNamer.cs) adds a "Let chat name it" button there;
pressing it sends Core a "mix_vote" event with the game's own name ideas, the names already used in
the save and the mix's effects. plugin.py then runs one MixVote from this file:

  1. "suggest" (``mix_suggest_sec`` seconds, skipped when 0): chatters type !mixname <name>. Each
     chatter has one idea (a new one replaces theirs); the same idea from several chatters counts
     once with more backers.
  2. "vote" (``mix_vote_sec`` seconds): up to ``mix_options`` names, best-backed ideas first, the
     rest filled with the game's ideas (with ``mix_keep_game_name`` one game idea is always there).
     Chat votes !1 !2 ... (or !vote 2) and can change its vote.
  3. "done": names ranked by votes (ties keep option order). The mod tries them in that order until
     the game accepts one (a name the save already has is refused by the game).

This file is pure logic (no network, no chat): plugin.py feeds it chat and the clock and sends what
``mod_state()`` / ``board()`` return to the mod (POST /mixvote) and the overlays (a "board" packet,
drawn like Core's own polls). Times are ``time.time()`` seconds, so the board's ``ends_at`` matches
the chat games' boards. Keep the state names in sync with MixNamer.cs.
"""

from __future__ import annotations

import re
from typing import Any, Optional

BOARD_ID = "schedule1_mix"     # board id on the overlays / Stream Rooms (Core's own poll uses "poll")
MIN_NAME_LEN = 2               # shorter ideas are refused
MAX_IDEAS = 200                # ideas kept per vote (a busy chat can't grow it forever)

# Characters a mix name may use: the game turns the name into a file-safe id, and its UI font has
# no emoji or most non-Latin scripts. Anything else is dropped from an idea.
_NOT_ALLOWED = re.compile(r"[^A-Za-z0-9 '&.\-]")
_SPACES = re.compile(r"\s+")


def clean_mix_name(raw: Any, max_len: int = 24) -> str:
    """A chatter's idea as a name the game can show: allowed characters only, single spaces, at most
    ``max_len`` characters (cut at a word when possible), each word capitalised like the game's own
    names ("blue dream" -> "Blue Dream"). "" when nothing usable is left."""
    text = _SPACES.sub(" ", _NOT_ALLOWED.sub("", str(raw or ""))).strip(" '.-&")
    if len(text) > max_len:
        cut = text[:max_len]
        text = (cut.rsplit(" ", 1)[0] if " " in cut else cut).strip(" '.-&")
    if len(text) < MIN_NAME_LEN:
        return ""
    return " ".join(w[:1].upper() + w[1:] for w in text.split(" "))


def has_blocked_word(name: str, blocked: Any) -> bool:
    """True when ``name`` contains any word of the ``mix_blocked_words`` setting (a list, or
    "word, word" text), ignoring case. Parts of words count too ("ass" blocks "Grass"), so the list
    should hold whole words the streamer never wants on a product."""
    if isinstance(blocked, str):
        blocked = blocked.split(",")
    low = name.lower()
    return any(str(w).strip().lower() in low for w in (blocked or []) if str(w).strip())


class MixVote:
    """One "chat names the new mix" round. plugin.py makes a new one per button press."""

    def __init__(self, game_names: list[str], taken: list[str], effects: list[str], value: str,
                 now: float, suggest_sec: float, vote_sec: float, options: int = 4,
                 keep_game_name: bool = True):
        # The game's ideas, its own pick for this mix first (MixNamer.cs GameIdeas); taken ones dropped.
        self.taken = {str(t).strip().lower() for t in taken or [] if str(t).strip()}
        seen: set[str] = set()
        self.game_names: list[str] = []
        for n in game_names or []:
            n = str(n).strip()
            if n and n.lower() not in self.taken and n.lower() not in seen:
                seen.add(n.lower())
                self.game_names.append(n)
        self.effects = [str(e) for e in effects or [] if str(e).strip()][:8]
        self.value = str(value or "")
        self.vote_sec = max(5.0, float(vote_sec))
        self.n_options = max(2, min(9, int(options)))     # !1 .. !9
        self.keep_game_name = bool(keep_game_name)
        # ideas: lower-case name -> {"name", "by": set of person keys, "order"}; person -> lower name
        self.ideas: dict[str, dict] = {}
        self.idea_of: dict[str, str] = {}
        self._next_order = 0                              # first-come order of ideas (ties)
        self.options: list[str] = []
        self.votes: dict[str, int] = {}                   # person key -> option index (0-based)
        self.ranked: list[str] = []                       # set when done
        if suggest_sec and float(suggest_sec) > 0:
            self.phase = "suggest"
            self.ends_at = now + max(5.0, float(suggest_sec))
        else:
            self.phase = "vote"
            self._open_vote(now)

    # ------------------------------------------------------------------ chat

    def suggest(self, person: str, raw: Any, max_len: int = 24, blocked: Any = None) -> tuple[bool, str]:
        """!mixname: (True, the cleaned name) or (False, why not, said back in chat)."""
        if self.phase != "suggest":
            return False, "name ideas are closed, vote with " + ("!1 !2 ..." if self.phase == "vote" else "the next mix")
        name = clean_mix_name(raw, max_len)
        if not name:
            return False, "that name can't be used in the game (letters, numbers, spaces, ' & . - only)"
        low = name.lower()
        if low in self.taken:
            return False, f"{name} is already a product in this save"
        if has_blocked_word(name, blocked):
            return False, "that name isn't allowed"
        old = self.idea_of.get(person)
        if old == low:
            return True, name
        if old is not None:                               # one idea per chatter: drop their old one
            idea = self.ideas.get(old)
            if idea:
                idea["by"].discard(person)
                if not idea["by"]:
                    del self.ideas[old]
        if low not in self.ideas:
            if len(self.ideas) >= MAX_IDEAS:
                return False, "there are enough ideas already, vote on them soon"
            self._next_order += 1
            self.ideas[low] = {"name": name, "by": set(), "order": self._next_order}
        self.ideas[low]["by"].add(person)
        self.idea_of[person] = low
        return True, name

    def vote(self, person: str, index: int) -> bool:
        """!<n> / !vote <n> with a 0-based index; False when no vote is open or the number is wrong."""
        if self.phase != "vote" or not 0 <= index < len(self.options):
            return False
        self.votes[person] = index
        return True

    # ------------------------------------------------------------------ clock

    def tick(self, now: float) -> Optional[str]:
        """Move on when the phase's time is up. Returns the new phase ("vote" / "done") or None."""
        if self.phase in ("done", "stopped") or now < self.ends_at:
            return None
        if self.phase == "suggest":
            self._open_vote(now)
            if self.phase == "vote":
                return "vote"
            return "done"                                 # only one name possible: nothing to vote on
        self._finish()
        return "done"

    def stop(self) -> None:
        """The streamer stopped it in the game (button again, or closed the naming screen)."""
        self.phase = "stopped"

    def _open_vote(self, now: float) -> None:
        """Build the options: best-backed ideas (most chatters, then earliest), then the game's ideas."""
        ideas = sorted(self.ideas.values(), key=lambda i: (-len(i["by"]), i["order"]))
        room = self.n_options - (1 if self.keep_game_name and self.game_names else 0)
        opts = [i["name"] for i in ideas[:room]]
        for g in self.game_names:
            if len(opts) >= self.n_options:
                break
            if g.lower() not in {o.lower() for o in opts}:
                opts.append(g)
        self.options = opts
        self.ends_at = now + self.vote_sec
        self.phase = "vote"
        if len(opts) < 2:                                 # 0 or 1 name: no vote, that's the answer
            self._finish()

    def counts(self) -> list[int]:
        out = [0] * len(self.options)
        for i in self.votes.values():
            if 0 <= i < len(out):
                out[i] += 1
        return out

    def _finish(self) -> None:
        """Rank the options by votes; equal votes keep option order (best-backed idea first)."""
        c = self.counts()
        order = sorted(range(len(self.options)), key=lambda i: (-c[i], i))
        self.ranked = [self.options[i] for i in order]
        # the game's other ideas go last, so the mod has more to try if every option is refused
        self.ranked += [g for g in self.game_names if g not in self.ranked]
        self.phase = "done"

    @property
    def winner(self) -> str:
        return self.ranked[0] if self.ranked else ""

    def winner_votes(self) -> int:
        if not self.ranked or self.winner not in self.options:
            return 0
        return self.counts()[self.options.index(self.winner)]

    # ------------------------------------------------------------------ what others see

    def mod_state(self, now: float, confirm: bool) -> dict:
        """Body for POST /mixvote (BridgeServer.cs reads the same field names into Shared.MixState)."""
        if self.phase == "suggest":
            rows = [{"name": i["name"], "votes": len(i["by"])}
                    for i in sorted(self.ideas.values(), key=lambda i: (-len(i["by"]), i["order"]))[:6]]
        else:
            c = self.counts()
            rows = [{"name": o, "votes": c[i]} for i, o in enumerate(self.options)]
        return {"state": self.phase, "ends_in": max(0, round(self.ends_at - now)), "options": rows,
                "winner": self.winner, "ranked": self.ranked[:12], "confirm": bool(confirm)}

    def board(self, prefix: str = "!") -> dict:
        """A "board" packet's data for the overlays (same shape as core/chat_games Poll.show)."""
        if self.phase == "suggest":
            ideas = sorted(self.ideas.values(), key=lambda i: (-len(i["by"]), i["order"]))[:8]
            total = max(1, sum(len(i["by"]) for i in ideas))
            lines = [{"key": str(n + 1), "label": i["name"], "value": len(i["by"]),
                      "pct": round(len(i["by"]) / total, 3), "note": f"{len(i['by'])}", "win": False}
                     for n, i in enumerate(ideas)]
            return {"id": BOARD_ID, "kind": "bars", "title": "🧪 Name the new mix", "lines": lines,
                    "footer": f"Suggest: {prefix}mixname <name>", "state": "open", "ends_at": self.ends_at}
        c = self.counts()
        total = max(1, sum(c))
        best = max(c) if c else 0
        closed = self.phase in ("done", "stopped")
        lines = [{"key": str(i + 1), "label": f"{i + 1}. {o}", "value": c[i], "pct": round(c[i] / total, 3),
                  "note": f"{c[i]} ({round(100 * c[i] / total)}%)",
                  "win": self.phase == "done" and o == self.winner and (best > 0 or len(self.options) < 2)}
                 for i, o in enumerate(self.options)]
        if self.phase == "done":
            footer = f"{self.winner} wins"
        elif self.phase == "stopped":
            footer = "Stopped by the streamer"
        else:
            footer = "Vote: " + " ".join(f"{prefix}{i + 1}" for i in range(len(self.options)))
        return {"id": BOARD_ID, "kind": "bars", "title": "🧪 Name the new mix", "lines": lines, "footer": footer,
                "state": "closed" if closed else "open", "ends_at": None if closed else self.ends_at}
