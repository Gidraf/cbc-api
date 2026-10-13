import pytest

from app.services.speech_text import for_speech


@pytest.mark.parametrize("written, spoken", [
    ("A diver at -18 m rises 12 m.", "A diver at -18 metres rises 12 metres."),
    ("Sugar costs KSh 1,592 and milk Kshs. 60 per litre.", "Sugar costs 1,592 Kenya shillings and milk 60 Kenya shillings per litre."),
    ("It costs KES 1 or 500/= each.", "It costs 1 Kenya shilling or 500 shillings each."),
    ("Sugar costs KSh 40/kg.", "Sugar costs 40 Kenya shillings per kilogram."),
    ("A matatu travels 60 km/h for 2 hrs.", "A matatu travels 60 kilometres per hour for 2 hours."),
    ("It fell from 25°C. Angle = 45°, the other 1°.", "It fell from 25 degrees Celsius. Angle = 45 degrees, the other 1 degree."),
    ("Area 24 cm², volume 8 cm^3, field 2 ha.", "Area 24 square centimetres, volume 8 cubic centimetres, field 2 hectares."),
    ("Give your answer in cm.", "Give your answer in centimetres."),
    ("The rope is 1 m long and 2.5m wide.", "The rope is 1 metre long and 2.5 metres wide."),
    ("e.g. 15% of them, i.e. 6, etc.", "for example 15 percent of them, that is 6, et cetera"),
    ("It took 45 min at 5 m/s.", "It took 45 minutes at 5 metres per second."),
    ("Plant 3/4 of it, then 1/2, then 17/12; 7/30 remain.", "Plant 3 quarters of it, then one half, then 17 twelfths; 7 over 30 remain."),
    ("Add 2 1/4 kg; it is -5/8. Born 12/10/2026.", "Add 2 and one quarter kilograms; it is negative 5 eighths. Born 12/10/2026."),
])
def test_the_voice_says_the_words(written, spoken):
    assert for_speech(written) == spoken


@pytest.mark.parametrize("algebra", ["Solve 3m + 2 = 11.", "Simplify 4m - 2m.", "Find 3m when m is 2",
                                     "Solve for m: 3 m = 12", "Expand 2(3g + 4)"])
def test_algebra_is_not_read_as_units(algebra):
    assert for_speech(algebra) == algebra


def test_kiswahili_reads_in_kiswahili_order():
    assert for_speech("Shamba lina urefu wa 12 m na bei ni KSh 500.", "sw") == \
        "Shamba lina urefu wa mita 12 na bei ni shilingi za Kenya 500."
    assert for_speech("Punguzo la 20%", "sw") == "Punguzo la asilimia 20"


def test_reading_twice_changes_nothing():
    once = for_speech("Sugar at KSh 40/kg, 3 kg, 25°C, 60 km/h, in cm.")
    assert for_speech(once) == once


def test_the_walkthrough_narrates_in_words():
    from app.services import play_engine as P

    w = P.walkthrough({"question_text": "Sugar costs KSh 120 per kg. How much for 3 kg?", "expression": "120 * 3",
                       "curriculum": {"subject": "Mathematics"}})
    assert w["scenes"][0]["say"] == "Sugar costs 120 Kenya shillings per kilogram. How much for 3 kilograms?"
    assert w["scenes"][0]["text"].startswith("Sugar costs KSh 120")   # the board keeps the notation
