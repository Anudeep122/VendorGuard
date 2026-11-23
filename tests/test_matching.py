from app import matching as m


def test_normalize():
    assert m.normalize("Harlow & Finch Consulting Ltd.") == "harlow finch consulting"
    assert m.normalize("Meridian Precision Components Pvt Ltd") == m.normalize("Meridian Precision Components Private Limited")
    assert m.normalize("Volgograd Trading Co") == "volgograd trading"
    assert m.normalize("") == "" and m.normalize(None) == ""


def test_similarity():
    assert m.similarity("Meridian Precision Components Pvt Ltd", "Meridian Precision Components Private Limited") == 1.0
    assert m.similarity("Markus Vogel", "Brightwave Analytics GmbH") < 0.5
    assert m.similarity("Acme Industries LLC", "Acme Industries Inc") >= 0.9
    assert m.similarity("", "x") == 0.0


def test_acronym():
    assert m.is_acronym_match("NLS Pvt Ltd", "Northwind Logistics Solutions Pvt Ltd")
    assert m.is_acronym_match("NLS", "Northwind Logistics Solutions")
    assert not m.is_acronym_match("ABC", "Northwind Logistics Solutions")
    assert not m.is_acronym_match("N", "Northwind")


def test_looks_like_person():
    assert m.looks_like_person("Markus Vogel")
    assert m.looks_like_person("Daniel J. Whitaker")
    assert not m.looks_like_person("Brightwave Analytics GmbH")
    assert not m.looks_like_person("Sandstone Trading")
    assert not m.looks_like_person("Acme Supplies")
    assert not m.looks_like_person("markus vogel")
    assert not m.looks_like_person("Markus")
    assert not m.looks_like_person("Meridian Precision", company_name="Meridian Precision Components")


def test_watchlist_score_catches_variant():
    assert m.name_match_score("Volgograd Trade Company", "Volgograd Trading Co") >= 0.88
    assert m.name_match_score("Meridian Precision Components Pvt Ltd", "Red Meridian Holdings Ltd") < 0.88
