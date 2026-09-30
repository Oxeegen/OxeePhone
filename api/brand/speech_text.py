"""Text preparation for Local Models TTS: pronunciation dictionary and French
normalization.

Applied only to the text sent for synthesis (``LocalModelsTTSService`` and the
voice preview), so transcripts and the LLM context keep what the agent wrote
("14h30"), while the caller hears "quatorze heures trente".

French numbers are spelled out here (traditional spelling: "vingt et un",
"quatre-vingts", "deux cents") rather than with num2words (LGPL).
"""

import re

# ------------------------------------------------------------------ numbers

_UNITS = [
    "zéro",
    "un",
    "deux",
    "trois",
    "quatre",
    "cinq",
    "six",
    "sept",
    "huit",
    "neuf",
    "dix",
    "onze",
    "douze",
    "treize",
    "quatorze",
    "quinze",
    "seize",
    "dix-sept",
    "dix-huit",
    "dix-neuf",
]
_TENS = {2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante"}


def _below_100(n: int) -> str:
    if n < 20:
        return _UNITS[n]
    tens, unit = divmod(n, 10)
    if tens in (7, 9):  # soixante-dix..., quatre-vingt-dix...
        base = "soixante" if tens == 7 else "quatre-vingt"
        rest = 10 + unit
        if tens == 7 and unit == 1:
            return "soixante et onze"
        return f"{base}-{_UNITS[rest]}"
    if tens == 8:
        return "quatre-vingts" if unit == 0 else f"quatre-vingt-{_UNITS[unit]}"
    word = _TENS[tens]
    if unit == 0:
        return word
    if unit == 1:
        return f"{word} et un"
    return f"{word}-{_UNITS[unit]}"


def _below_1000(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    if hundreds == 0:
        return _below_100(rest)
    if hundreds == 1:
        head = "cent"
    else:
        head = f"{_UNITS[hundreds]} cent" + ("s" if rest == 0 else "")
    return head if rest == 0 else f"{head} {_below_100(rest)}"


def number_to_words(n: int, *, feminine: bool = False) -> str:
    """Spell out 0 <= n < 1e12 in French."""
    if n < 0:
        return "moins " + number_to_words(-n, feminine=feminine)
    if n == 0:
        return "zéro"
    parts = []
    for value, singular, plural in (
        (10**9, "milliard", "milliards"),
        (10**6, "million", "millions"),
    ):
        count, n = divmod(n, value)
        if count:
            parts.append(
                f"{number_to_words(count)} {singular if count == 1 else plural}"
            )
    thousands, n = divmod(n, 1000)
    if thousands:
        # "mille" is invariable and never "un mille"; "quatre-vingt mille".
        words = "" if thousands == 1 else _below_1000(thousands)
        words = re.sub(r"(vingt|cent)s$", r"\1", words)
        parts.append(f"{words} mille".strip())
    if n:
        parts.append(_below_1000(n))
    text = " ".join(parts)
    if feminine and re.search(r"(^|[ -])un$", text):
        text = text[:-2] + "une"
    return text


def ordinal_to_words(n: int, *, feminine: bool = False) -> str:
    if n == 1:
        return "première" if feminine else "premier"
    words = re.sub(r"(vingt|cent)s$", r"\1", number_to_words(n))
    if words.endswith("cinq"):
        return words + "uième"
    if words.endswith("neuf"):
        return words[:-1] + "vième"
    words = words.removesuffix("e")
    return words + "ième"


def _digits_to_words(digits: str) -> str:
    """ "05" -> "zéro cinq", "50" -> "cinquante" (leading zeros read aloud)."""
    stripped = digits.lstrip("0")
    zeros = ["zéro"] * (len(digits) - len(stripped))
    return " ".join(zeros + ([number_to_words(int(stripped))] if stripped else []))


# ---------------------------------------------------------------- rewriters

_MONTHS = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]

_PHONE = re.compile(
    r"(?<![\d+])(?:\+33\s?(?:\(0\)\s?)?|0)([1-9])((?:[\s.\-]?\d{2}){4})(?!\d)"
)
_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?\b")
_TIME = re.compile(r"\b([01]?\d|2[0-3])(?:\s?[hH]\s?([0-5]\d)?|:([0-5]\d))(?![\w:])")
_MONEY = re.compile(r"(\d+(?:[\s  ]\d{3})*)(?:[.,](\d{1,2}))?\s?(?:€|EUR\b|euros?\b)")
_PERCENT = re.compile(r"(\d+)(?:[.,](\d+))?\s?%")
_ORDINAL = re.compile(r"\b(\d+)\s?(er|re|ère|ème|eme|e)\b")
_DECIMAL = re.compile(r"\b(\d+),(\d+)\b")
_GROUPED = re.compile(r"\b\d{1,3}(?:[\s  ]\d{3})+\b")
# Standalone 1-4 digit numbers; not parts of decimals, codes or percentages.
_INTEGER = re.compile(r"(?<!\w)(?<!\d[.,])\d{1,4}(?!\w|[.,]\d|\s?%)")

# Case-sensitive abbreviations; "M." only before a capitalized name.
_ABBREVIATIONS = [
    (re.compile(r"\bDr\b\.?"), "docteur"),
    (re.compile(r"\bPr\b\.?"), "professeur"),
    (re.compile(r"\bMmes\b"), "mesdames"),
    (re.compile(r"\bMme\b\.?"), "madame"),
    (re.compile(r"\bMlle\b\.?"), "mademoiselle"),
    (re.compile(r"\bMM\.\s(?=[A-ZÉÈ])"), "messieurs "),
    (re.compile(r"\bM\.\s(?=[A-ZÉÈ])"), "monsieur "),
    (re.compile(r"\b(?:RDV|rdv|Rdv)\b"), "rendez-vous"),
    (re.compile(r"\b[nN]°\s?"), "numéro "),
    (re.compile(r"\b[tT]él\b\.?"), "téléphone"),
    (re.compile(r"\betc\.", re.IGNORECASE), "et cetera"),
    (re.compile(r"\s&\s"), " et "),
]


def _phone(match: re.Match) -> str:
    pairs = re.findall(r"\d{2}", match.group(2))
    spoken = [f"zéro {_UNITS[int(match.group(1))]}"] + [
        _digits_to_words(p) for p in pairs
    ]
    return ", ".join(spoken)


def _date(match: re.Match) -> str:
    day, month, year = int(match.group(1)), int(match.group(2)), match.group(3)
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return match.group(0)
    words = f"{'premier' if day == 1 else number_to_words(day)} {_MONTHS[month - 1]}"
    if year:
        full = int(year) + (2000 if len(year) == 2 else 0)
        words += f" {number_to_words(full)}"
    return words


def _time(match: re.Match) -> str:
    hours = int(match.group(1))
    minutes = match.group(2) or match.group(3)
    if hours == 0 and not minutes:
        return "minuit"
    if hours == 12 and not minutes:
        return "midi"
    words = f"{number_to_words(hours, feminine=True)} heure{'s' if hours > 1 else ''}"
    if minutes and int(minutes):
        words += f" {number_to_words(int(minutes))}"
    return words


def _money(match: re.Match) -> str:
    euros = int(re.sub(r"\D", "", match.group(1)))
    words = f"{number_to_words(euros)} euro{'s' if euros > 1 else ''}"
    if match.group(2):
        cents = int(match.group(2).ljust(2, "0"))
        if cents:
            words += f" {number_to_words(cents)}"
    return words


def _percent(match: re.Match) -> str:
    words = number_to_words(int(match.group(1)))
    if match.group(2):
        words += f" virgule {_digits_to_words(match.group(2))}"
    return f"{words} pour cent"


def _ordinal(match: re.Match) -> str:
    n, suffix = int(match.group(1)), match.group(2)
    if n == 1 and suffix in ("re", "ère"):
        return "première"
    if n == 1 and suffix == "er":
        return "premier"
    if suffix in ("er", "re", "ère"):
        return match.group(0)
    return ordinal_to_words(n)


def normalize_french(text: str) -> str:
    for pattern, replacement in _ABBREVIATIONS:
        text = pattern.sub(replacement, text)
    text = _PHONE.sub(_phone, text)
    text = _DATE.sub(_date, text)
    text = _TIME.sub(_time, text)
    text = _MONEY.sub(_money, text)
    text = _PERCENT.sub(_percent, text)
    text = _ORDINAL.sub(_ordinal, text)
    text = _DECIMAL.sub(
        lambda m: (
            f"{number_to_words(int(m.group(1)))} virgule {_digits_to_words(m.group(2))}"
        ),
        text,
    )
    text = _GROUPED.sub(
        lambda m: number_to_words(int(re.sub(r"\D", "", m.group(0)))), text
    )
    text = _INTEGER.sub(lambda m: number_to_words(int(m.group(0))), text)
    return text


# ------------------------------------------------------ pronunciation dictionary


def parse_pronunciations(raw: str | None) -> list[tuple[str, str]]:
    """Parse "word = pronunciation" lines (blank lines and # comments skipped)."""
    entries = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for separator in ("=>", "→", "="):
            if separator in line:
                source, target = (part.strip() for part in line.split(separator, 1))
                if source:
                    entries.append((source, target))
                break
    # Longest first so "Dr Martin" wins over "Dr".
    return sorted(entries, key=lambda entry: len(entry[0]), reverse=True)


def apply_pronunciations(text: str, entries: list[tuple[str, str]]) -> str:
    for source, target in entries:
        pattern = rf"(?<!\w){re.escape(source)}(?!\w)"
        text = re.sub(pattern, lambda _m, t=target: t, text, flags=re.IGNORECASE)
    return text


def prepare_speech_text(
    text: str,
    *,
    language: str | None,
    pronunciations: list[tuple[str, str]] | None = None,
) -> str:
    """Dictionary first (it can override normalization), then French rules."""
    if pronunciations:
        text = apply_pronunciations(text, pronunciations)
    if (language or "fr").lower().startswith("fr"):
        text = normalize_french(text)
    return text
