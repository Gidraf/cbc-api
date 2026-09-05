r"""Repair the backslashes in a model's JSON before it is parsed.

A model asked for LaTeX inside JSON writes `"$3 \times 4$"`. That is not what
it means. JSON reads `\t` as a TAB, so `json.loads` returns `$3 <TAB>imes 4$`
— and nothing downstream can tell that from text the model actually wrote. It
renders as "3 imes 4" on the page, in a Grade 9 mathematics lesson.

The failures, in order of how badly they end:

    \times      -> TAB + "imes"          silent; prints as "imes"
    \text       -> TAB + "ext"           silent; prints as "ext"
    \frac       -> FORMFEED + "rac"      silent; prints as "rac"
    \neq        -> NEWLINE + "eq"        silent; breaks the line
    \right      -> RETURN + "ight"       silent
    \alpha      -> invalid escape        the whole generation fails to parse
    \underline  -> invalid \uXXXX        the whole generation fails to parse

The silent ones are the reason this file exists. A hard parse error is visible
and gets retried; a tab in the middle of an equation is shipped to a class.

`repair` doubles a backslash the model left single. It only ever ADDS
backslashes inside string literals, so JSON that was already correct — a model
that properly wrote `\\times`, or a genuine `\n` line break — passes through
untouched.
"""
from __future__ import annotations

import re

# The escapes JSON itself defines. A backslash followed by anything else is
# invalid JSON, so doubling it is always the right repair.
_JSON_ESCAPES = frozenset('"\\/bfnrtu')

# LaTeX commands that begin with a letter JSON also uses as an escape. For
# these the text is genuinely ambiguous — `\n` could be a line break the model
# meant, or the start of `\neq` — so they are repaired by NAME rather than by
# guess. Anything not on this list keeps whatever the model wrote.
_COLLIDING_COMMANDS = (
    # t: the most common in this system's content by a wide margin
    "times", "textbf", "textit", "textrm", "textstyle", "text", "theta",
    "tan", "tfrac", "therefore", "tilde", "triangle", "top", "to",
    # f
    "frac", "forall", "flat", "frown",
    # n
    "nsubseteq", "newline", "nabla", "notin", "neq", "not", "nmid", "nu", "ne",
    # r
    "rightarrow", "rangle", "rfloor", "rceil", "right", "rho",
    # b
    "boldsymbol", "because", "begin", "binom", "bullet", "boxed", "beta",
    "bigg", "bmod", "big", "bar",
    # u
    "underbrace", "underline", "uparrow", "upsilon", "unicode",
)

# Longest first, so `\ne` cannot match before `\neq` has been tried.
_COLLIDING = sorted(_COLLIDING_COMMANDS, key=len, reverse=True)
_COLLIDING_RE = re.compile(r"\\(" + "|".join(_COLLIDING) + r")\b")


def _even_backslashes_before(text: str, index: int) -> bool:
    """True when the backslash at `index` is itself unescaped."""
    count = 0
    probe = index - 1
    while probe >= 0 and text[probe] == "\\":
        count += 1
        probe -= 1
    return count % 2 == 0


def repair(raw: str) -> str:
    r"""JSON with every LaTeX backslash escaped the way JSON requires.

    >>> repair(r'{"a": "$3 \times 4$"}')
    '{"a": "$3 \\\\times 4$"}'
    >>> repair(r'{"a": "line\nbreak"}')          # a real escape is left alone
    '{"a": "line\\nbreak"}'
    >>> repair(r'{"a": "$3 \\times 4$"}')        # already correct
    '{"a": "$3 \\\\times 4$"}'
    """
    if not raw or "\\" not in raw:
        return raw

    # 1. Commands that collide with a JSON escape, by name.
    def _double_named(match: re.Match[str]) -> str:
        if not _even_backslashes_before(match.string, match.start()):
            return match.group(0)  # already escaped
        return "\\\\" + match.group(1)

    out = _COLLIDING_RE.sub(_double_named, raw)

    # 2. Everything else: a backslash before a character JSON does not define
    #    an escape for. `\alpha`, `\pi`, `\cdot`, `\%`, `\(`. These are invalid
    #    JSON as written, so doubling them cannot change a valid document.
    result: list[str] = []
    i = 0
    length = len(out)
    while i < length:
        char = out[i]
        if char != "\\":
            result.append(char)
            i += 1
            continue
        nxt = out[i + 1] if i + 1 < length else ""
        if nxt == "\\":
            result.append("\\\\")  # an escaped backslash, kept whole
            i += 2
            continue
        if nxt in _JSON_ESCAPES:
            result.append(char)
            i += 1
            continue
        # Not a JSON escape at all — the model meant a literal backslash.
        result.append("\\\\")
        i += 1

    return "".join(result)
