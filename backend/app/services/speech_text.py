"""What the narrator says, not what the board shows.

A paper writes "KSh 1,592", "12 m", "45°" and "60 km/h"; a voice reading
those aloud says "K-S-H", "twelve em", or skips the degree sign. Every line
that is spoken passes through `for_speech` first, so the board keeps the
notation a learner must read and the voice says the words a teacher would.

Single-letter units (m, g, l, s, h) are the risky ones: "3m + 2 = 11" is
algebra, not metres. They are expanded only when written apart from their
number ("12 m") and not followed by an operator; written together ("3m")
they are left as they are. Multi-letter units (cm, km, kg) are expanded
either way — "3cm + 4cm" is centimetres whichever way it is written.

Kiswahili gets Kiswahili words in Kiswahili order: "mita 12", "shilingi za
Kenya 500".
"""
from __future__ import annotations

import re

VERSION = "s1"  # in every narration cache key: change the rules, re-speak

# abbreviation: (singular, plural) — British spelling, as Kenyan schools use.
_UNITS_EN: dict[str, tuple[str, str]] = {
    "mm": ("millimetre", "millimetres"), "cm": ("centimetre", "centimetres"), "dm": ("decimetre", "decimetres"),
    "m": ("metre", "metres"), "km": ("kilometre", "kilometres"),
    "mg": ("milligram", "milligrams"), "g": ("gram", "grams"), "kg": ("kilogram", "kilograms"),
    "ml": ("millilitre", "millilitres"), "mL": ("millilitre", "millilitres"), "cl": ("centilitre", "centilitres"),
    "l": ("litre", "litres"), "L": ("litre", "litres"), "ltr": ("litre", "litres"), "ltrs": ("litre", "litres"),
    "ha": ("hectare", "hectares"), "ac": ("acre", "acres"),
    "s": ("second", "seconds"), "sec": ("second", "seconds"), "secs": ("second", "seconds"),
    "min": ("minute", "minutes"), "mins": ("minute", "minutes"),
    "h": ("hour", "hours"), "hr": ("hour", "hours"), "hrs": ("hour", "hours"),
    "wk": ("week", "weeks"), "wks": ("week", "weeks"), "yr": ("year", "years"), "yrs": ("year", "years"),
    "kWh": ("kilowatt hour", "kilowatt hours"), "kW": ("kilowatt", "kilowatts"), "W": ("watt", "watts"),
    "V": ("volt", "volts"), "N": ("newton", "newtons"), "Pa": ("pascal", "pascals"), "J": ("joule", "joules"),
    "kJ": ("kilojoule", "kilojoules"), "cal": ("calorie", "calories"), "kcal": ("kilocalorie", "kilocalories"),
    "pcs": ("piece", "pieces"), "pkts": ("packet", "packets"), "pkt": ("packet", "packets"),
    "doz": ("dozen", "dozen"), "ft": ("foot", "feet"), "yd": ("yard", "yards"), "mi": ("mile", "miles"),
}
_UNITS_SW: dict[str, str] = {
    "mm": "milimita", "cm": "sentimita", "m": "mita", "km": "kilomita", "mg": "miligramu", "g": "gramu",
    "kg": "kilogramu", "ml": "mililita", "mL": "mililita", "l": "lita", "L": "lita", "ha": "hekta",
    "s": "sekunde", "sec": "sekunde", "min": "dakika", "mins": "dakika", "h": "saa", "hr": "saa", "hrs": "saa",
}
_SINGLE = {"m", "g", "l", "L", "s", "h", "W", "V", "N", "J"}
_MULTI = sorted((u for u in _UNITS_EN if u not in _SINGLE), key=len, reverse=True)

_NUM = r"(?<![\w.])(-?\d[\d,]*(?:\.\d+)?)"
_OPERATOR_AFTER = r"(?!\s*[-+×x*/÷=^(]\s*[\w(])"


def _plural(number: str, pair: tuple[str, str]) -> str:
    return pair[0] if number.lstrip("-") in ("1", "1.0") else pair[1]


def for_speech(text: str, lang: str = "en") -> str:
    """The line as a teacher would say it."""
    if not text:
        return text
    t = str(text)
    sw = lang.startswith("sw")
    t = _currency(t, sw)
    t = _temperatures_and_angles(t, sw)
    t = _rates(t, sw)
    t = _units_after_numbers(t, sw)
    if not sw:
        t = _fractions(t)
    if not sw:
        t = _units_after_words(t)
        t = _words(t)
    t = _percent_sw(t) if sw else re.sub(r"\s*%", " percent", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _percent_sw(t: str) -> str:
    return re.sub(_NUM + r"\s*%", lambda m: f"asilimia {m.group(1)}", t)


def _currency(t: str, sw: bool) -> str:
    kenya = "shilingi za Kenya" if sw else None

    def kes(m: re.Match) -> str:
        n = m.group("n")
        if sw:
            return f"{kenya} {n}"
        return f"{n} Kenya {'shilling' if n.lstrip('-') == '1' else 'shillings'}"

    # KSh 1,592 · Kshs. 500 · KES 200 · Ksh.200 · K.Sh 50
    t = re.sub(r"\b(?:K\.?\s?[Ss]hs?|KSH|KES|Kes|kes)\.?\s*(?P<n>-?\d[\d,]*(?:\.\d+)?)", kes, t)
    # 500/= — the shilling sign on a Kenyan price tag
    t = re.sub(_NUM + r"\s*/=", lambda m: (f"shilingi {m.group(1)}" if sw else f"{m.group(1)} shillings"), t)
    # Sh 50 · Shs. 50 (shillings, no country)
    t = re.sub(r"\b[Ss]hs?\.?\s*(?P<n>\d[\d,]*(?:\.\d+)?)",
               lambda m: (f"shilingi {m.group('n')}" if sw else f"{m.group('n')} shillings"), t)
    for sign, word in (("US$", "US dollars"), ("$", "dollars"), ("£", "pounds"), ("€", "euros")):
        t = re.sub(re.escape(sign) + r"\s*(\d[\d,]*(?:\.\d+)?)", lambda m, w=word: f"{m.group(1)} {w}", t)
    t = re.sub(r"\b(\d[\d,]*(?:\.\d+)?)\s*(?:USD)\b", r"\1 US dollars", t)
    # KSh on its own: "in KSh", "the price (KSh)"
    t = re.sub(r"\b(?:KSh|Kshs?|KES)\b\.?", "shilingi za Kenya" if sw else "Kenya shillings", t)
    return t


def _temperatures_and_angles(t: str, sw: bool) -> str:
    deg = "nyuzi" if sw else "degrees"
    t = re.sub(_NUM + r"\s*°\s*C\b", lambda m: (f"nyuzi {m.group(1)} za Selsiasi" if sw else
                                                 f"{m.group(1)} degrees Celsius"), t)
    t = re.sub(_NUM + r"\s*°\s*F\b", lambda m: f"{m.group(1)} degrees Fahrenheit", t)
    t = re.sub(_NUM + r"\s*(?:°|\^\\circ|\^\{\\circ\}|\s?deg\b\.?|\s?degs\b\.?)",
               lambda m: (f"{deg} {m.group(1)}" if sw else
                          f"{m.group(1)} {'degree' if m.group(1) == '1' else 'degrees'}"), t)
    return t.replace("°C", " degrees Celsius").replace("°", " degrees")


def _rates(t: str, sw: bool) -> str:
    if sw:
        return re.sub(_NUM + r"\s*km/h(?:r)?\b|" + _NUM + r"\s*kph\b",
                      lambda m: f"kilomita {m.group(1) or m.group(2)} kwa saa", t)
    named = {"km/h": "kilometres per hour", "km/hr": "kilometres per hour", "kph": "kilometres per hour",
             "kmph": "kilometres per hour", "m/s": "metres per second", "m/s²": "metres per second squared",
             "m/s^2": "metres per second squared", "km/l": "kilometres per litre", "km/L": "kilometres per litre",
             "l/min": "litres per minute", "g/cm³": "grams per cubic centimetre", "kg/m³": "kilograms per cubic metre"}
    for abbr in sorted(named, key=len, reverse=True):
        t = re.sub(_NUM + r"\s*" + re.escape(abbr) + r"(?![\w²³])", lambda m, w=named[abbr]: f"{m.group(1)} {w}", t)
        t = re.sub(r"(?<![\w/])" + re.escape(abbr) + r"(?![\w/²³])", named[abbr], t)
    # Anything else per something: "KSh 40/kg" has become "40 Kenya shillings/kg"
    t = re.sub(r"/\s*(kg|g|km|m|cm|l|L|ml|litre|hr|h|day|week|month|year|person|item|unit|dozen|packet)\b",
               lambda m: " per " + (_UNITS_EN.get(m.group(1), (m.group(1),))[0]), t)
    return t


def _units_after_numbers(t: str, sw: bool) -> str:
    def unit(m: re.Match, single: bool) -> str:
        number, abbr = m.group(1), m.group(2)
        power = (m.group(3) if m.re.groups >= 3 else "") or ""
        if sw:
            word = _UNITS_SW.get(abbr)
            if not word:
                return m.group(0)
            pre = {"2": "za mraba ", "²": "za mraba ", "3": "za ujazo ", "³": "za ujazo "}.get(power.lstrip("^"), "")
            return f"{word} {pre}{number}".replace("  ", " ").strip()
        pair = _UNITS_EN[abbr]
        word = _plural(number, pair)
        p = power.lstrip("^")
        if p in ("2", "²"):
            return f"{number} square {pair[1] if word == pair[1] else pair[0]}"
        if p in ("3", "³"):
            return f"{number} cubic {pair[1] if word == pair[1] else pair[0]}"
        return f"{number} {word}"

    multi = "|".join(re.escape(u) for u in _MULTI)
    t = re.sub(_NUM + r"\s?(" + multi + r")(\^?[23²³])?(?![\w])", lambda m: unit(m, False), t)
    # A letter that also stands alone in the sentence — "when m is 2" — is a
    # variable there, never a unit.
    variables = set(re.findall(r"(?<![\w])(?<!\d )(?<!\d)([a-zA-Z])(?![\w'])", t))
    letters = sorted(u for u in _SINGLE if u not in variables)
    if not letters:
        return t
    single = "|".join(re.escape(u) for u in letters)
    # Single letters only with a space, and not where algebra continues.
    t = re.sub(_NUM + r" (" + single + r")(\^?[23²³])?(?![\w'])" + _OPERATOR_AFTER, lambda m: unit(m, True), t)
    # Written together, only where a plain word follows — "2.5m wide",
    # "a 3m rope" — and never at the end of an expression ("4m - 2m.").
    t = re.sub(_NUM + r"(" + single + r")(?=\s+(?!and\b|or\b|is\b)[a-z]{2,})", lambda m: unit(m, True), t)
    return t


def _units_after_words(t: str) -> str:
    """'in cm', 'per kg', '(km)' — a unit named without a number."""
    multi = "|".join(re.escape(u) for u in _MULTI)

    def named(m: re.Match) -> str:
        lead, abbr, power = m.group(1), m.group(2), m.group(3) or ""
        pair = _UNITS_EN[abbr]
        word = pair[0] if lead.strip().lower() == "per" else pair[1]
        p = power.lstrip("^")
        if p in ("2", "²"):
            word = "square " + word
        elif p in ("3", "³"):
            word = "cubic " + word
        return f"{lead}{word}"

    t = re.sub(r"(\b(?:in|of|per|into|to|from|and|or)\s+|\()(" + multi + r"|m|g|l|L|h)(\^?[23²³])?(?=[\s).,;:!?]|$)",
               named, t)
    return t


_ORDINAL = {2: ("half", "halves"), 3: ("third", "thirds"), 4: ("quarter", "quarters"), 5: ("fifth", "fifths"),
            6: ("sixth", "sixths"), 7: ("seventh", "sevenths"), 8: ("eighth", "eighths"), 9: ("ninth", "ninths"),
            10: ("tenth", "tenths"), 11: ("eleventh", "elevenths"), 12: ("twelfth", "twelfths"),
            13: ("thirteenth", "thirteenths"), 14: ("fourteenth", "fourteenths"), 15: ("fifteenth", "fifteenths"),
            16: ("sixteenth", "sixteenths"), 20: ("twentieth", "twentieths"), 24: ("twenty-fourth", "twenty-fourths"),
            25: ("twenty-fifth", "twenty-fifths"), 100: ("hundredth", "hundredths"), 1000: ("thousandth", "thousandths")}


def _fractions(t: str) -> str:
    """3/4 is "3 quarters", 1/2 "one half", 7/30 "7 over 30"."""
    def say(m: re.Match) -> str:
        neg, n, d = m.group(1) or "", int(m.group(2)), int(m.group(3))
        if d == 0:
            return m.group(0)
        words = _ORDINAL.get(d)
        if words:
            spoken = f"one {words[0]}" if n == 1 else f"{n} {words[1]}"
        else:
            spoken = f"{n} over {d}"
        return ("negative " if neg else "") + spoken

    # A mixed number first: 2 1/4 is "2 and one quarter".
    t = re.sub(r"(?<![\w/.])(\d+)\s+(\d+)/(\d+)(?![\w/=])",
               lambda m: f"{m.group(1)} and " + say(re.match(r"()(\d+)/(\d+)", f"{m.group(2)}/{m.group(3)}")), t)
    return re.sub(r"(?<![\w/.])(-)?(\d+)\s*/\s*(\d+)(?![\w/=]|\.\d)", say, t)


_WORDS: tuple[tuple[str, str], ...] = (
    (r"\be\.g\.?(?=\s|,|$)", "for example"), (r"\bi\.e\.?(?=\s|,|$)", "that is"),
    (r"\betc\.?(?=\s|,|$)", "et cetera"), (r"\bapprox\.?(?=\s)", "approximately"),
    (r"\bNo\.\s?(?=\d)", "number "), (r"\bno\.\s?(?=\d)", "number "),
    (r"\bFig\.\s?(?=\d)", "Figure "), (r"\bfig\.\s?(?=\d)", "figure "), (r"\bEx\.\s?(?=\d)", "Example "),
    (r"\bQn\.?\s?(?=\d)", "question "), (r"\bvs\.?(?=\s)", "versus"), (r"\bavg\.?(?=\s)", "average"),
    (r"\bmax\.(?=\s)", "maximum"), (r"\bdiag\.(?=\s)", "diagram"), (r"\bqty\.?(?=\s)", "quantity"),
    (r"\s&\s", " and "), (r"\bp\.m\.?(?=\s|,|$)", "P M"), (r"\ba\.m\.?(?=\s|,|$)", "A M"),
)


def _words(t: str) -> str:
    for pattern, word in _WORDS:
        t = re.sub(pattern, word, t)
    return t
