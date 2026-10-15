"""Django approval storage retains ownership without mirroring the gateway."""


def test_model_approval_ownership_and_removal(domain_services):
    catalog = domain_services.catalog
    domain_services.classes.set_enabled(True)
    catalog.approve("shared-name", ["Public"], "definition-one")
    assert catalog.get("shared-name")["owned_by_keeplane"] is False
    catalog.approve("shared-name", ["Public"], "definition-one", owned_by_keeplane=True)
    assert catalog.get("shared-name")["owned_by_keeplane"] is True
    assert catalog.remove("shared-name")
    assert catalog.get("shared-name") is None
