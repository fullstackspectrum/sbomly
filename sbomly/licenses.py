"""Rough copyleft classification of licence expressions.

This is a triage signal for a reviewer, not legal advice: it decides which
licence changes deserve a second look.
"""

from __future__ import annotations

import re

NONE, WEAK, STRONG, NETWORK = 0, 1, 2, 3

LABELS = {
    NONE: "permissive or unknown",
    WEAK: "weak copyleft",
    STRONG: "strong copyleft",
    NETWORK: "network copyleft",
}

# Checked in order; the first match wins, so the narrower names come first
# (LGPL before GPL, AGPL before GPL).
_ID_RULES: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"^(AGPL|SSPL)", re.I), NETWORK),
    (re.compile(r"^(LGPL|MPL|EPL|CDDL|CPL|MS-RL|EUPL)", re.I), WEAK),
    (re.compile(r"^(GPL|OSL|RPL|Sleepycat|CC-BY-SA|CC-BY-NC-SA)", re.I), STRONG),
]

# Free-text names, for SBOMs that carry "GNU General Public License v3"
# instead of an SPDX id.
_NAME_RULES: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"affero|server side public", re.I), NETWORK),
    (re.compile(r"(lesser|library) general public|mozilla public|eclipse public|common development and distribution", re.I), WEAK),
    (re.compile(r"general public licen[cs]e|\bgnu gpl\b", re.I), STRONG),
]

# Exceptions that let you link without the copyleft reaching your code.
_LINKING_EXCEPTION = re.compile(r"classpath|linking|gcc-exception|llvm-exception|autoconf", re.I)


def _classify_term(term: str) -> int:
    term = term.strip()
    if not term:
        return NONE
    parts = re.split(r"\s+WITH\s+", term, maxsplit=1, flags=re.I)
    base = parts[0]
    exception = parts[1] if len(parts) > 1 else ""
    level = NONE
    for pattern, rule_level in _ID_RULES:
        if pattern.match(base):
            level = rule_level
            break
    else:
        for pattern, rule_level in _NAME_RULES:
            if pattern.search(base):
                level = rule_level
                break
    if level == STRONG and _LINKING_EXCEPTION.search(exception):
        return WEAK
    return level


def normalise(expression: str) -> str:
    """A comparison key: 'MPL-2.0 AND MIT' and 'mit and mpl-2.0' are the same licence.

    Only flat expressions (one operator, no brackets) are reordered; anything
    more involved is compared as written, give or take case and spacing.
    """
    text = " ".join(expression.split()).casefold()
    if "(" in text or ")" in text:
        return text
    for op in (" and ", " or "):
        terms = text.split(op)
        if len(terms) > 1 and not any((" and " if op == " or " else " or ") in t for t in terms):
            return op.join(sorted(terms))
    return text


def copyleft_level(expression: str) -> int:
    """The least restrictive option the expression allows.

    'MIT OR GPL-3.0' lets you pick MIT, so it scores as permissive.
    'MIT AND GPL-3.0' binds you to both, so it scores as strong copyleft.
    AND binds tighter than OR, as in the SPDX spec.
    """
    tokens = re.findall(r"\(|\)|[^\s()]+", expression)
    pos = 0

    def peek() -> str:
        return tokens[pos].upper() if pos < len(tokens) else ""

    def atom() -> int:
        nonlocal pos
        if peek() == "(":
            pos += 1
            level = either()
            if peek() == ")":
                pos += 1
            return level
        # A licence term runs until an operator or bracket, so free-text
        # names with spaces and "X WITH exception" stay in one piece.
        words = []
        while pos < len(tokens) and peek() not in ("AND", "OR", "(", ")"):
            words.append(tokens[pos])
            pos += 1
        if not words and pos < len(tokens) and peek() != ")":
            pos += 1  # A stray operator; skip it rather than loop.
        return _classify_term(" ".join(words))

    def both() -> int:
        nonlocal pos
        level = atom()
        while peek() == "AND":
            pos += 1
            level = max(level, atom())
        return level

    def either() -> int:
        nonlocal pos
        level = both()
        while peek() == "OR":
            pos += 1
            level = min(level, both())
        return level

    return either() if tokens else NONE
