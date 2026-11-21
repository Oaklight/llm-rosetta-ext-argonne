"""The manifest builder writes what the shim manifest v1 spec says, and only that.

The gateway trusts the manifest to pick a version its core can load and to pin
the archive by digest, so the builder's rules are tested here: the records
match the tree, a published record never changes, a changed archive needs a
new version, and the validator refuses what the spec does not allow.
"""

from __future__ import annotations

import copy
import importlib.util
import shutil
import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_COMMIT = "0" * 40
_STAMP = "2026-11-21T00:00:00Z"


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


archives = _load("build_shim_archive")
builder = _load("build_manifest")
ROOT = archives.repo_root()

needs_tomllib = pytest.mark.skipif(
    sys.version_info < (3, 11), reason="the builder reads vendors.toml with tomllib"
)


def _build(previous=None):
    return builder.build_manifest(
        ROOT, previous=previous, commit=_COMMIT, generated_at=_STAMP
    )


@needs_tomllib
def test_the_built_manifest_is_valid_and_covers_every_vendor():
    manifest, added = _build()
    assert builder.validate_manifest(manifest) == []
    assert (
        sorted(manifest["vendors"]) == archives.vendors() == ["alcf", "argo", "asksage"]
    )
    assert manifest["source"] == "argonne"
    for vendor, entry in manifest["vendors"].items():
        (record,) = entry["versions"]
        assert record["archive"] in added
        assert record["shims"] == [n for n, _ in archives.declared_shims(vendor)]
        assert record["requires"] == {"surface": 1, "ir": 1}
        assert record["maturity"] == "stable"
        assert "org:argonne" in record["tags"]
        assert record["conformance"] == {"date": None, "result": "none"}
        assert record["promoted_to"] is None


@needs_tomllib
def test_the_record_digest_is_the_archive_digest():
    manifest, added = _build()
    for entry in manifest["vendors"].values():
        record = entry["versions"][0]
        assert archives.sha256_hex(added[record["archive"]]) == record["sha256"]


@needs_tomllib
def test_the_installed_core_satisfies_every_requires():
    """The gateway's rule: surface equal, ir not above the running core's."""
    from llm_rosetta.contracts import IR_VERSION, SURFACE_VERSION

    manifest, _ = _build()
    for entry in manifest["vendors"].values():
        requires = entry["versions"][0]["requires"]
        assert requires["surface"] == SURFACE_VERSION
        assert requires["ir"] <= IR_VERSION


@needs_tomllib
def test_an_unchanged_archive_keeps_its_published_record():
    first, _ = _build()
    published = copy.deepcopy(first)
    published["vendors"]["argo"]["versions"][0]["commit"] = "1" * 40
    second, added = _build(previous=published)
    assert added == {}
    assert second["vendors"] == published["vendors"]


@needs_tomllib
def test_a_changed_archive_under_a_published_version_is_refused():
    first, _ = _build()
    first["vendors"]["alcf"]["versions"][0]["sha256"] = "f" * 64
    with pytest.raises(builder.ManifestError, match="Bump vendors.alcf.version"):
        _build(previous=first)


@needs_tomllib
def test_a_new_version_is_prepended_and_history_kept():
    first, _ = _build()
    older = copy.deepcopy(first)
    for entry in older["vendors"].values():
        record = entry["versions"][0]
        vendor = record["archive"].split("/")[1].removesuffix(".tar.gz")
        record["version"] = "0.3.0"
        record["archive"] = f"0.3.0/{vendor}.tar.gz"
    older["vendors"]["retired"] = copy.deepcopy(older["vendors"]["argo"])
    for record in older["vendors"]["retired"]["versions"]:
        record["archive"] = "0.3.0/retired.tar.gz"
        record["shims"] = ["retired--chat_completions"]
    manifest, added = _build(previous=older)
    assert builder.validate_manifest(manifest) == []
    assert len(added) == 3
    for vendor in ("alcf", "argo", "asksage"):
        versions = [r["version"] for r in manifest["vendors"][vendor]["versions"]]
        assert versions == ["0.4.1", "0.3.0"]
    assert manifest["vendors"]["retired"] == older["vendors"]["retired"]


@needs_tomllib
def test_write_outputs_lays_out_the_dist_branch(tmp_path: Path):
    manifest, added = _build()
    builder.write_outputs(tmp_path, manifest, added, "0.4.1")
    for vendor in ("alcf", "argo", "asksage"):
        archive = tmp_path / "0.4.1" / f"{vendor}.tar.gz"
        assert archive.is_file()
        digest = (tmp_path / "0.4.1" / f"{vendor}.tar.gz.sha256").read_text()
        assert digest.split()[0] == archives.sha256_hex(archive.read_bytes())
    latest = json.loads((tmp_path / "manifest.json").read_text())
    assert latest == json.loads((tmp_path / "0.4.1" / "manifest.json").read_text())
    assert builder.main(["--check", str(tmp_path / "manifest.json")]) == 0


@needs_tomllib
def test_a_published_release_snapshot_is_never_overwritten(tmp_path: Path):
    manifest, added = _build()
    builder.write_outputs(tmp_path, manifest, added, "0.4.0")
    manifest["generated_at"] = "2026-11-22T00:00:00Z"
    with pytest.raises(builder.ManifestError, match="already published"):
        builder.write_outputs(tmp_path, manifest, {}, "0.4.0")


@needs_tomllib
def test_a_tag_that_disagrees_with_the_package_is_refused():
    with pytest.raises(builder.ManifestError, match="tag says"):
        builder.main(["--dry-run", "--expect-version", "9.9.9", "--commit", _COMMIT])


def _valid_document() -> dict:
    return {
        "manifest_version": 1,
        "source": "argonne",
        "repo": "https://github.com/Oaklight/llm-rosetta-shim-argonne",
        "generated_at": _STAMP,
        "vendors": {
            "argo": {
                "versions": [
                    {
                        "version": "0.4.0",
                        "commit": _COMMIT,
                        "archive": "0.4.0/argo.tar.gz",
                        "sha256": "a" * 64,
                        "requires": {"surface": 1, "ir": 1},
                        "shims": ["argo--chat_completions"],
                        "tags": ["org:argonne"],
                        "maturity": "stable",
                        "since": "2026-11-21",
                        "conformance": {"date": None, "result": "none"},
                        "promoted_to": None,
                    }
                ]
            }
        },
    }


def test_the_reference_document_is_valid():
    assert builder.validate_manifest(_valid_document()) == []


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("sha256",), "xyz", "sha256"),
        (("commit",), "abc", "commit"),
        (("maturity",), "core", "maturity"),
        (("archive",), "0.4.0/other.tar.gz", "archive"),
        (("requires",), {"surface": 1}, "requires"),
        (("requires",), {"surface": True, "ir": 1}, "requires"),
        (("shims",), [], "shims"),
        (("shims",), ["other--chat_completions"], "every name must be 'argo'"),
        (("since",), "21/11/2026", "since"),
        (("conformance",), {"date": None, "result": "pass"}, "needs a date"),
        (("conformance",), {"date": "2026-11-20", "result": "ok"}, "result"),
        (("promoted_to",), "0.15.0", "promoted_to"),
        (("extra",), 1, "unknown keys"),
    ],
)
def test_the_validator_refuses_a_bad_record(path, value, message):
    doc = _valid_document()
    doc["vendors"]["argo"]["versions"][0][path[0]] = value
    problems = builder.validate_manifest(doc)
    assert any(message in p for p in problems), problems


def test_the_validator_refuses_versions_out_of_order():
    doc = _valid_document()
    older = copy.deepcopy(doc["vendors"]["argo"]["versions"][0])
    older.update(version="0.5.0", archive="0.5.0/argo.tar.gz")
    doc["vendors"]["argo"]["versions"].append(older)
    assert any("newest first" in p for p in builder.validate_manifest(doc))


def test_the_validator_refuses_a_wrong_manifest_version():
    doc = _valid_document()
    doc["manifest_version"] = 2
    assert any("manifest_version" in p for p in builder.validate_manifest(doc))


#: What each vendor's provider.yaml publishes as its display fields.
EXPECTED_DISPLAY = {
    "alcf": {"label": "ALCF", "logo": "https://cdn.jsdelivr.net/gh/Oaklight/llm-rosetta-shim-argonne@v0.4.0/assets/alcf.svg"},
    "argo": {"label": "Argo", "logo": "https://cdn.jsdelivr.net/gh/Oaklight/llm-rosetta-shim-argonne@v0.4.0/assets/argo.svg"},
    "asksage": {"label": "AskSage", "logo": "https://cdn.jsdelivr.net/gh/Oaklight/llm-rosetta-shim-argonne@v0.4.0/assets/asksage.webp"},
}
#: Per-vendor repositories that are archived; no mark may point at them.
ARCHIVED = ("llm-rosetta-shim-argo@", "llm-rosetta-shim-alcf", "llm-rosetta-shim-asksage")


# -- Display fields (Oaklight/llm-rosetta#1671) ------------------------------


def _vendor_root(root: Path, vendor: str) -> Path:
    return archives.vendor_dir(vendor, root) / "provider.yaml"


@needs_tomllib
def test_every_vendor_record_carries_its_label_and_logo_from_provider_yaml():
    manifest, _ = _build()
    for vendor, expected in EXPECTED_DISPLAY.items():
        record = manifest["vendors"][vendor]["versions"][0]
        assert {k: record.get(k) for k in ("label", "logo")} == expected, vendor
    for entry in manifest["vendors"].values():
        logo = entry["versions"][0].get("logo")
        if logo:
            # Pinned: an immutable record's mark cannot change underneath it.
            assert "@latest" not in logo and "@main" not in logo, logo
            assert not any(old in logo for old in ARCHIVED), logo


def test_the_vendor_root_is_read_with_a_yaml_parser(tmp_path: Path):
    """Quoting, a folded line and a comment the old regex reader missed."""
    vendor_root = _vendor_root(ROOT, "argo")
    text = vendor_root.read_text()
    folded = (
        'group_label: >-\n  Folded\n  Name\nlogo: "https://a.example/x.svg"  # pinned\n'
    )
    work = tmp_path / "repo"
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "dist", "__pycache__"))
    target = _vendor_root(work, "argo")
    target.write_text(folded + "\n".join(
        line for line in text.splitlines() if not line.startswith(("group_label:", "logo:"))
    ) + "\n")
    assert builder.vendor_display("argo", work) == {
        "label": "Folded Name",
        "logo": "https://a.example/x.svg",
    }


@needs_tomllib
def test_a_vendor_without_a_label_or_logo_fails_the_release(tmp_path: Path):
    work = tmp_path / "repo"
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "dist", "__pycache__"))
    target = _vendor_root(work, "argo")
    target.write_text("\n".join(
        line for line in target.read_text().splitlines()
        if not line.startswith(("group_label:", "logo:"))
    ) + "\n")
    with pytest.raises(builder.ManifestError) as caught:
        builder.build_manifest(work, commit="c" * 40, generated_at="2026-11-21T00:00:00Z")
    message = str(caught.value)
    assert "argo: no group_label" in message
    assert "argo: no logo" in message


def test_the_no_logo_list_is_checked_both_ways(monkeypatch):
    records = {"acme": {"label": "Acme", "logo": "https://a.example/a.svg"}, "bare": {"label": "Bare"}}
    monkeypatch.setattr(builder, "NO_LOGO", frozenset({"bare"}))
    assert builder.display_problems(records) == []
    monkeypatch.setattr(builder, "NO_LOGO", frozenset({"acme", "ghost"}))
    problems = builder.display_problems(records)
    assert "acme: has a logo; drop it from NO_LOGO" in problems
    assert any("bare: no logo" in p for p in problems)
    assert any("'ghost'" in p for p in problems)


def test_the_display_rule_is_cores_not_a_copy():
    """A bad value is refused by core's schema; the builder keeps no copy."""
    contract = pytest.importorskip("llm_rosetta.contracts.shim_manifest")
    if "label" not in contract.load_manifest_schema()["$defs"]["release"]["properties"]:
        pytest.skip("this core predates the display fields")
    assert not any(hasattr(builder, n) for n in ("_LABEL", "_LOGO", "_LABEL_MAX", "_LOGO_MAX"))
    record = {
        "version": "0.1.0",
        "commit": "c" * 40,
        "archive": "0.1.0/acme.tar.gz",
        "sha256": "0" * 64,
        "requires": {"surface": 1, "ir": 1},
        "shims": ["acme--chat_completions"],
        "tags": [],
        "maturity": "beta",
        "since": "2026-11-21",
        "conformance": {"date": None, "result": "none"},
        "promoted_to": None,
    }
    doc = {
        "manifest_version": 1,
        "source": builder.SOURCE,
        "repo": builder.REPO,
        "generated_at": "2026-11-21T00:00:00Z",
        "vendors": {"acme": {"versions": [record]}},
    }
    assert builder.validate_manifest(doc) == []
    for field, value in (("logo", "http://insecure.example/x.svg"), ("label", "x" * 81)):
        bad = copy.deepcopy(doc)
        bad["vendors"]["acme"]["versions"][0][field] = value
        problems = builder.validate_manifest(bad)
        assert any(p.startswith("core schema:") and field in p for p in problems), problems
