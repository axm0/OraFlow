from pathlib import Path

import pytest

from oraflow.db import _dsn_with_resolved_hosts, _dsn_with_timeout
from oraflow.tns import TnsCatalog, format_descriptor, format_tnsnames_file, parse_tnsnames

FIXTURE = Path(__file__).parent / "fixtures" / "tnsnames_sample.ora"
ROOT = Path(__file__).parents[1]
ROOT_TNS = ROOT / "tnsnames.ora"
ROOT_CLOUD_TNS = ROOT / "cloud-tnsnames.ora"
NETWORK_ADMIN = ROOT / "oracle-network" / "admin"
EXTENSION_NETWORK_ADMIN = ROOT / "extensions" / "vscode" / "oracle-network" / "admin"


def test_parse_tnsnames_extracts_aliases_and_fields():
    entries = parse_tnsnames(FIXTURE)

    assert len(entries) == 6
    prod = next(entry for entry in entries if entry.alias == "ACME-PROD.ZDWACMP01")
    assert prod.hosts == ["juno-admin.example.com"]
    assert prod.port == 1521
    assert prod.sid == "dwacmp01"
    assert prod.customer == "ACME"
    assert prod.environment == "PROD"
    assert prod.sid_token == "ZDWACMP01"
    assert prod.host_group == "juno"


def test_duplicate_aliases_get_stable_disambiguating_keys():
    entries = parse_tnsnames(FIXTURE)
    duplicate_19cdb = [entry for entry in entries if entry.alias == "19CDB"]

    assert len(duplicate_19cdb) == 2
    assert {entry.key for entry in duplicate_19cdb} == {"19CDB@anaconda", "19CDB@pluto"}
    assert all(entry.duplicate_alias for entry in duplicate_19cdb)


def test_catalog_resolves_unique_alias_and_rejects_ambiguous_alias():
    catalog = TnsCatalog.load(FIXTURE)

    assert catalog.resolve("ACME-PROD.ZDWACMP01").host_group == "juno"
    assert catalog.resolve("19CDB@pluto").hosts == ["pluto-admin.example.com"]
    with pytest.raises(KeyError, match="Ambiguous alias"):
        catalog.resolve("19CDB")


def test_catalog_search_filters_and_ranks():
    catalog = TnsCatalog.load(FIXTURE)

    matches = catalog.search("acme", environment="PROD", limit=5)
    assert [entry.alias for entry in matches] == ["ACME-PROD.ZDWACMP01"]

    cloud = catalog.search("cloud service", limit=2)
    assert cloud[0].service_name == "cloud.example.com"


def test_catalog_search_filters_by_deployment_source_tag(tmp_path):
    cloud_fixture = Path(__file__).parent / "fixtures" / "cloud-tnsnames_sample.ora"
    entries = parse_tnsnames(FIXTURE) + parse_tnsnames(cloud_fixture)
    catalog = TnsCatalog(entries)

    cloud_only = catalog.search("46", source_tag="cloud", limit=5)
    onprem_only = catalog.search("acme", source_tag="onprem", limit=5)

    # Filter is the invariant we care about: every returned entry must come
    # from the requested deployment, regardless of how the fuzzy ranker
    # ordered them. (process.extract always returns up to `limit` rows even
    # when the query is a poor match, so we don't assert on emptiness.)
    assert cloud_only and all(entry.source_tag == "cloud" for entry in cloud_only)
    assert onprem_only and all(entry.source_tag == "onprem" for entry in onprem_only)
    assert all(entry.source_tag == "cloud" for entry in catalog.search("acme", source_tag="cloud", limit=5))
    assert all(entry.source_tag == "onprem" for entry in catalog.search("46", source_tag="onprem", limit=5))


def test_cloud_ndc_aliases_infer_environment_from_dq_token():
    cloud_fixture = Path(__file__).parent / "fixtures" / "cloud-tnsnames_sample.ora"
    catalog = TnsCatalog(parse_tnsnames(cloud_fixture))

    assert catalog.resolve("txndcd46").environment == "DEV"
    assert catalog.resolve("txndcq46").environment == "QA"


@pytest.mark.parametrize(
    ("path", "expected_source_tag"),
    [
        (ROOT_TNS, "onprem"),
        (ROOT_CLOUD_TNS, "cloud"),
        (NETWORK_ADMIN / "tnsnames.ora", "onprem"),
        (NETWORK_ADMIN / "cloud-tnsnames.ora", "cloud"),
        (EXTENSION_NETWORK_ADMIN / "tnsnames.ora", "onprem"),
        (EXTENSION_NETWORK_ADMIN / "cloud-tnsnames.ora", "cloud"),
    ],
)
def test_each_shipped_tns_file_maps_every_entry_to_expected_deployment(path, expected_source_tag):
    entries = parse_tnsnames(path)

    assert entries, f"Expected at least one TNS entry in {path}"
    assert {entry.source_tag for entry in entries} == {expected_source_tag}
    assert all(entry.source_path == str(path.resolve()) for entry in entries)


def test_real_cloud_ndc_46_aliases_infer_dev_and_qa_from_dq_token():
    catalog = TnsCatalog(parse_tnsnames(ROOT_CLOUD_TNS))

    dev46 = catalog.resolve("txndcd46")
    qa46 = catalog.resolve("txndcq46")

    assert dev46.source_tag == "cloud"
    assert dev46.environment == "DEV"
    assert qa46.source_tag == "cloud"
    assert qa46.environment == "QA"


def test_real_onprem_numeric_aliases_infer_environment_prefix():
    catalog = TnsCatalog(parse_tnsnames(ROOT_TNS))

    assert catalog.resolve("QA11.ZDWNDCQ11").source_tag == "onprem"
    assert catalog.resolve("QA11.ZDWNDCQ11").environment == "QA"
    assert catalog.resolve("QA11.TXNDCQ11").source_tag == "onprem"
    assert catalog.resolve("QA11.TXNDCQ11").environment == "QA"


def test_info_counts_duplicates_and_groups():
    info = TnsCatalog.load(FIXTURE).info()

    assert info.total_entries == 6
    assert info.duplicate_aliases["19CDB"] == 2
    assert info.environments["PROD"] == 1
    assert info.host_groups["juno"] == 2


def test_dsn_with_timeout_injects_oracle_net_timeout_and_normalizes_server_default():
    descriptor = """
    (DESCRIPTION=
      (ADDRESS=(PROTOCOL=TCP)(HOST=10.0.0.10)(PORT=1521))
      (CONNECT_DATA=(SERVER=default)(SERVICE_NAME=example.com))
    )
    """

    updated = _dsn_with_timeout(descriptor, 7)

    assert "(CONNECT_TIMEOUT=7)" in updated
    assert "(TRANSPORT_CONNECT_TIMEOUT=7)" in updated
    assert "(RETRY_COUNT=0)" in updated
    assert "(SERVER=DEDICATED)" in updated
    assert "SERVER=default" in descriptor


def test_dsn_with_resolved_hosts_rewrites_unresolvable_host(monkeypatch):
    descriptor = "(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=example.internal)(PORT=1537))(CONNECT_DATA=(SID=x)))"

    monkeypatch.setattr("oraflow.db._resolve_host", lambda host: "10.1.2.3" if host == "example.internal" else None)

    assert "(HOST=10.1.2.3)" in _dsn_with_resolved_hosts(descriptor)


def test_format_descriptor_preserves_descriptor_fields():
    original = "(DESCRIPTION=(ADDRESS_LIST=(LOAD_BALANCE=on)(ADDRESS=(PROTOCOL=TCP)(HOST=h1)(PORT=1521)))(CONNECT_DATA=(SERVICE_NAME=s1)))"
    formatted = format_descriptor(original)

    assert "\n" in formatted
    assert "(LOAD_BALANCE=on)" in formatted
    assert "(HOST=h1)" in formatted
    assert "(SERVICE_NAME=s1)" in formatted


def test_format_tnsnames_file_preserves_semantic_entries(tmp_path):
    source = tmp_path / "tnsnames.ora"
    source.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    before = [(entry.alias, entry.hosts, entry.port, entry.sid, entry.service_name) for entry in parse_tnsnames(source)]

    assert format_tnsnames_file(source) is True
    after = [(entry.alias, entry.hosts, entry.port, entry.sid, entry.service_name) for entry in parse_tnsnames(source)]

    assert after == before
    assert format_tnsnames_file(source, check=True) is False


