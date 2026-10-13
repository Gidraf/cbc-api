import pytest

from app.services.latex_text import to_speech, to_unicode
from app.services.speech_text import for_speech


@pytest.mark.parametrize("latex, written", [
    (r"$\frac{3}{4} + \frac{2}{3}$", "3/4 + 2/3"),
    (r"$(3a^2)^3$", "(3a²)³"),
    (r"$\sqrt[3]{216} \times 2$", "∛216 × 2"),
    (r"$2x + 3 \le 12$", "2x + 3 ≤ 12"),
    (r"$\log_{10} 1000$", "log₁₀ 1000"),
    (r"An angle of $45^\circ$.", "An angle of 45°."),
    (r"$\frac{p^{11}}{p^6} = p^{11-6}$", "p¹¹/p⁶ = p¹¹⁻⁶"),
    (r"Work out $\\frac{7^8}{7^5}$", "Work out 7⁸/7⁵"),
    (r"$\text{KSh } 1{,}200$", "KSh 1,200"),
])
def test_the_board_writes_symbols_not_markup(latex, written):
    assert to_unicode(latex) == written


@pytest.mark.parametrize("latex, said", [
    (r"Simplify $(3a^2)^3$", "Simplify (3a squared) cubed"),
    (r"Evaluate $\sqrt[3]{216} \times 2$", "Evaluate the cube root of 216 times 2"),
    (r"Solve $2x + 3 \le 12$", "Solve 2x plus 3 is less than or equal to 12"),
    (r"Find $\log_{10} 1000$", "Find log to base 10 of 1000"),
    (r"$5^{-2}$", "5 to the power of negative 2"),
    (r"$\frac{7^8}{7^5}$", "7 to the power of 8 over 7 to the power of 5"),
    (r"$\sin 30^\circ = 0.5$", "sine 30 degrees equals 0.5"),
])
def test_the_voice_says_words_not_markup(latex, said):
    assert to_speech(latex) == said
    assert "\\" not in for_speech(latex) and "frac" not in for_speech(latex)


def test_units_and_fractions_still_read_naturally():
    assert for_speech(r"Area $24\ \text{cm}^2$ and $\frac{3}{4}$ of it") == "Area 24 square centimetres and 3 quarters of it"
    assert for_speech("(b) 5³ = 125 m³.") == "(b) 5 cubed equals 125 cubic metres."
