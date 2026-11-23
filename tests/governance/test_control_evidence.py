"""Each run's evidence pack carries what every RAIMS control must leave, field by field, read from
the run's own records (RAIMS Week 6: governance is what you can prove)."""

from __future__ import annotations

import json
from pathlib import Path


def test_the_evidence_pack_shows_each_raims_controls_minimum_evidence_for_the_run(lifecycle):
    pack = Path(lifecycle.evidence_pack)
    controls = json.loads((pack / "raims_controls.json").read_text(encoding="utf-8"))
    assert set(controls) == {"RM-01", "HO-01", "TR-01", "MO-01", "DG-01"}
    ho = controls["HO-01"]
    assert ho["complete"] and ho["evidence_owner"] == "Deployer reviewer"
    assert ho["fields"]["reviewer_id"]["value"] == "arb.keane"
    assert len(ho["fields"]["report_hash"]["value"]) == 64
    assert ho["fields"]["approve_or_reject_reason"]["value"]["decision"] == "approve"
    rm = controls["RM-01"]["fields"]
    assert rm["exception_or_hold"]["present"] and rm["decision"]["present"], "holds were decided"
    dg = controls["DG-01"]["fields"]
    assert dg["approved_source_and_version"]["value"][0]["source"]
    assert dg["three_checks"]["value"]["legal_claims"] >= 1
    tr = controls["TR-01"]["fields"]
    assert tr["source_and_locator"]["value"]["with_source_and_locator"] > 0
    assert controls["MO-01"]["fields"]["affected_run"]["value"] == lifecycle.run_id
    manifest = json.loads((pack / "MANIFEST.json").read_text(encoding="utf-8"))
    assert "raims_controls.json" in json.dumps(manifest), "hashed with the rest of the pack"
