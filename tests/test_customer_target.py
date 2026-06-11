from pathlib import Path

import pytest

from oraflow.config import get_settings
from oraflow.customer_catalog import (
    CustomerCatalog,
    derive_profile,
    parse_target_text,
)
from oraflow.target import (
    clear_active_target,
    get_active_target,
    resolve_target,
    set_active_target,
)
from oraflow.tns import TnsCatalog, parse_tnsnames

FIXTURE = Path(__file__).parent / "fixtures" / "tnsnames_sample.ora"
CLOUD_FIXTURE = Path(__file__).parent / "fixtures" / "cloud-tnsnames_sample.ora"


def _load_mixed_catalog() -> TnsCatalog:
    """Load onprem + duplicated cloud fixtures into one catalog.

    The real dev setup can load the same cloud aliases from both the source
    tree and the extension bundle. Duplicating the fixture here ensures target
    resolution collapses identical TNS descriptors but still refuses genuinely
    different aliases.
    """
    entries = parse_tnsnames(FIXTURE) + parse_tnsnames(CLOUD_FIXTURE) + parse_tnsnames(CLOUD_FIXTURE)
    return TnsCatalog(entries)


def _write_customers(path: Path) -> None:
    path.write_text(
        """
[acme]
display_name = "ACME Pharmacy"
aliases = ["acme", "acmepharm"]
default_env = "uat"
default_layer = "oltp"

[acme.env.uat]
tns_alias = "ACME-UAT.ZDWACMU01"
profile = "ONPREM.QA"
layer = "oltp"
deployment = "onprem"

[acme.env.prod]
tns_alias = "ACME-PROD.ZDWACMP01"
profile = "ONPREM.PROD"
deployment = "onprem"
requires_confirm = true

[acme.env.devcloud]
tns_alias = "txndcd46"
profile = "CLOUD.DEV"
deployment = "cloud"
""".strip(),
        encoding="utf-8",
    )


def test_customer_catalog_resolves_customer_env_layer(tmp_path):
    customers_path = tmp_path / "customers.toml"
    _write_customers(customers_path)
    catalog = CustomerCatalog.load(customers_path)
    tns = _load_mixed_catalog()

    target = catalog.resolve("acmepharm", "prod", "dw", tns)

    assert target.customer == "acme"
    assert target.display_name == "ACME Pharmacy"
    assert target.tns_alias == "ACME-PROD.ZDWACMP01"
    assert target.profile == "ONPREM.PROD"
    assert target.layer == "dw"
    assert target.requires_confirm is True
    assert target.deployment == "onprem"


def test_parse_target_text_extracts_env_and_layer():
    assert parse_target_text("use vanderbilt prod aud") == ("vanderbilt", "prod", "aud", None)


def test_parse_target_text_extracts_deployment_and_excludes_it_from_customer():
    # Compact input should still separate env + numeric target + deployment.
    assert parse_target_text("dev46 cloud") == ("46", "dev", None, "cloud")


def test_parse_target_text_extracts_spaced_env_number_and_deployment():
    assert parse_target_text("DEV 46 cloud") == ("46", "dev", None, "cloud")


def test_parse_target_text_extracts_env_layer_and_deployment_together():
    # When env is present as a bare token, all four slots populate.
    assert parse_target_text("acme dev oltp cloud") == ("acme", "dev", "oltp", "cloud")


def test_parse_target_text_normalizes_deployment_aliases():
    assert parse_target_text("vandy uat oci")[3] == "cloud"
    assert parse_target_text("vandy uat on-prem")[3] == "onprem"
    assert parse_target_text("vandy uat onpremise")[3] == "onprem"


def test_derive_profile_from_tns_source_and_env():
    entry = TnsCatalog.load(FIXTURE).resolve("ACME-PROD.ZDWACMP01")
    assert derive_profile(entry) == "ONPREM.PROD"


def test_derive_profile_uses_explicit_deployment_override():
    onprem_entry = TnsCatalog.load(FIXTURE).resolve("ACME-PROD.ZDWACMP01")
    # Forcing cloud despite an onprem source still computes a CLOUD.* profile.
    assert derive_profile(onprem_entry, "dev", deployment="cloud") == "CLOUD.DEV"


def test_resolve_target_picks_cloud_alias_when_deployment_specified(tmp_path):
    customers_path = tmp_path / "customers.toml"
    _write_customers(customers_path)
    catalog = CustomerCatalog.load(customers_path)
    tns = _load_mixed_catalog()

    target = catalog.resolve("acme", "devcloud", None, tns, deployment="cloud")

    assert target.tns_alias == "txndcd46"
    assert target.profile == "CLOUD.DEV"
    assert target.deployment == "cloud"


def test_resolve_refuses_when_requested_deployment_disagrees_with_env_entry(tmp_path):
    customers_path = tmp_path / "customers.toml"
    _write_customers(customers_path)
    catalog = CustomerCatalog.load(customers_path)
    tns = _load_mixed_catalog()

    with pytest.raises(KeyError, match="deployment"):
        # Env "uat" is declared deployment="onprem"; asking for cloud must fail.
        catalog.resolve("acme", "uat", None, tns, deployment="cloud")


def test_resolve_target_alias_shortcut_with_deployment(tmp_path, monkeypatch):
    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    get_settings.cache_clear()

    # No customers.toml — go straight through the alias-shortcut path. Both
    # cloud aliases contain "46", but env=DEV filters to txndcd46.
    target = resolve_target(
        "DEV 46 cloud",
        env=None,
        layer=None,
        customer_catalog=CustomerCatalog({}, None),
        tns_catalog=_load_mixed_catalog(),
    )

    assert target.deployment == "cloud"
    assert target.profile.startswith("CLOUD.")
    assert target.tns_alias.lower() == "txndcd46"
    get_settings.cache_clear()


def test_resolve_target_refuses_ambiguous_deployment_match(tmp_path, monkeypatch):
    # Two cloud entries (txndcd46 and txndcq46) both contain the substring
    # "46". Without env in the prompt, this remains ambiguous.
    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    get_settings.cache_clear()
    with pytest.raises(KeyError, match="Ambiguous"):
        resolve_target(
            "46 cloud",
            env=None,
            layer=None,
            customer_catalog=CustomerCatalog({}, None),
            tns_catalog=_load_mixed_catalog(),
        )
    get_settings.cache_clear()


def test_active_target_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("ORAFLOW_WORKSPACE_DIR", str(tmp_path))
    get_settings.cache_clear()
    customers_path = tmp_path / "customers.toml"
    _write_customers(customers_path)
    target = resolve_target(
        "acme uat",
        None,
        None,
        CustomerCatalog.load(customers_path),
        _load_mixed_catalog(),
    )

    saved = set_active_target(target)
    loaded = get_active_target()

    assert saved["customer"] == "acme"
    assert saved["deployment"] == "onprem"
    assert loaded and loaded["tns_alias"] == "ACME-UAT.ZDWACMU01"
    assert loaded["deployment"] == "onprem"
    assert clear_active_target()["cleared"] is True
    assert get_active_target() is None
    get_settings.cache_clear()





