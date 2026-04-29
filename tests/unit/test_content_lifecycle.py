from app.modules.content.service import _cadence_for


def test_cadence_for_known_source_types():
    assert _cadence_for("fcom") == 180
    assert _cadence_for("qrh") == 90
    assert _cadence_for("amm") == 180
    assert _cadence_for("sop") == 90
    assert _cadence_for("syllabus") == 60


def test_cadence_for_unknown_source_type_falls_back_to_default():
    assert _cadence_for("manual") == 90  # default
    assert _cadence_for("") == 90
