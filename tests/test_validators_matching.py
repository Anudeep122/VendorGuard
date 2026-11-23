from app import matching as m
from app import validators as v


def test_gstin_roundtrip_and_invalid():
    g = v.make_gstin("29", "ABCDE1234F")
    assert v.is_valid_gstin(g)
    assert g[2:12] == "ABCDE1234F"
    bad = g[:-1] + ("A" if g[-1] != "A" else "B")
    assert not v.is_valid_gstin(bad)
    assert not v.is_valid_gstin(v.make_gstin("45", "ABCDE1234F"))  # bad state code
    assert not v.is_valid_gstin("123")
    assert not v.is_valid_gstin(None)


def test_pan_ifsc():
    assert v.is_valid_pan("ABCDE1234F")
    assert not v.is_valid_pan("ABCD1234F")
    assert v.is_valid_ifsc("HDFC0004321")
    assert not v.is_valid_ifsc("HDFC1004321")


def test_iban():
    assert v.is_valid_iban("DE89370400440532013000")
    assert v.is_valid_iban("DE89 3704 0044 0532 0130 00")
    assert v.is_valid_iban("GB82WEST12345698765432")
    assert not v.is_valid_iban("DE89370400440532013001")
    assert not v.is_valid_iban("DE8937040044053201300")  # wrong length
    ae = v.make_iban("AE", "0331234567890123456")
    assert len(ae) == 23 and v.is_valid_iban(ae)
    de2 = v.make_iban("DE", "50010517540804123456".replace("5001051754", "1234567890")[:18])
    assert v.is_valid_iban(de2)


def test_aba():
    assert v.is_valid_aba("021000021")
    assert v.is_valid_aba(v.make_aba("02100002"))
    assert not v.is_valid_aba("021000022")
    assert not v.is_valid_aba("12345")


def test_other_formats():
    assert v.is_valid_swift("DEUTDEFF") and v.is_valid_swift("DEUTDEFF500")
    assert not v.is_valid_swift("DEUT1EFF")
    assert v.is_valid_ein("84-1234567") and not v.is_valid_ein("8412345")
    assert v.is_valid_gb_vat("GB123456789") and not v.is_valid_gb_vat("GB12345")
    assert v.is_valid_de_vat("DE123456789")
    assert v.is_valid_ae_trn("100123456700003") and not v.is_valid_ae_trn("1001")
    assert v.detect_taxid_country("GB123456789") == "GB"
    assert v.detect_taxid_country("garbage") is None
    assert v.is_valid_email("a@b.co") and not v.is_valid_email("a@b")
    assert v.is_valid_phone("+91 98765 43210") and not v.is_valid_phone("abc")
    assert v.is_valid_postal("SW1A 1AA", "GB") and not v.is_valid_postal("1234", "DE")
    assert v.is_valid_postal("", "AE")


def test_normalize_and_similarity():
    assert m.normalize("Meridian Precision Components Pvt. Ltd.") == "meridian precision components"
    assert m.normalize("Harlow & Finch Consulting Ltd") == "harlow finch consulting"
    assert m.similarity("Meridian Precision Components Pvt Ltd",
                        "Meridian Precision Components Private Limited") >= 0.99
    assert m.similarity("Volgograd Trade Company", "Volgograd Trading Co") >= 0.88
    assert m.similarity("Markus Vogel", "Brightwave Analytics GmbH") < 0.7
    assert m.similarity("", "x") == 0.0


def test_acronym():
    assert m.is_acronym_match("NLS Pvt Ltd", "Northwind Logistics Solutions Pvt Ltd")
    assert not m.is_acronym_match("XYZ Ltd", "Northwind Logistics Solutions Pvt Ltd")
    assert not m.is_acronym_match("N", "Northwind")


def test_looks_like_person():
    assert m.looks_like_person("Markus Vogel", "Brightwave Analytics GmbH")
    assert not m.looks_like_person("Vogel Trading", "Brightwave Analytics GmbH")
    assert not m.looks_like_person("Markus Vogel GmbH")
    assert not m.looks_like_person("Single")
    assert not m.looks_like_person("a b c d")
