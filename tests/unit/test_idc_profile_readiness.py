"""QA15: preparación de perfil y consumo único, todo sintético."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from tools.idc_diagnostic.profile_readiness import inspect_profile_readiness
from tools.idc_diagnostic.reader_attempt_lab import SyntheticReaderAttempt
from test_idc_issuer_auth import _make_chain
from test_idc_device_auth_lab import _payload, _sign, sample  # noqa: F401


def _profile(**changes):
    data = {
        "schema_version": 1,
        "doc_type": "lab.invalid.document",
        "namespace": "lab.invalid.attributes",
        "name_element": "lab_name",
        "number_element": "lab_number",
        "reader_auth": "unknown",
    }
    data.update(changes)
    return json.dumps(data).encode()


def _report(profile=None, **kwargs):
    report = inspect_profile_readiness(profile, **kwargs)
    assert report["verified_identity"] is False
    assert report["idc_verification_available"] is False
    assert report["iaca_trust_anchor_validated"] is False
    assert report["profile_authenticity_verified"] is False
    assert "lab.invalid" not in json.dumps(report)
    return report


def test_missing_profile():
    assert _report()["status"] == "profile_required"


def test_unknown_reader_auth():
    assert _report(_profile())["status"] == "reader_auth_policy_required"


@pytest.mark.parametrize("changes, status", [
    ({"schema_version": True}, "unsupported_profile_version"),
    ({"doc_type": "org.example.sample"}, "synthetic_or_placeholder_profile"),
    ({"name_element": "lab_number"}, "duplicate_profile_element"),
    ({"reader_auth": "maybe"}, "invalid_reader_auth_policy"),
    ({"unexpected": "field"}, "invalid_profile_fields"),
])
def test_invalid_profiles(changes, status):
    assert _report(_profile(**changes))["status"] == status


def test_duplicate_keys():
    data = _profile()[:-1] + b', "doc_type": "lab.invalid.other"}'
    assert _report(data)["status"] == "duplicate_profile_key"


def test_independent_pin_required():
    root, _, _ = _make_chain()
    assert _report(_profile(reader_auth="required"), candidate_iaca_der=root)[
        "status"
    ] == "independent_anchor_pin_required"


def test_wrong_pin():
    root, _, _ = _make_chain()
    assert _report(
        _profile(reader_auth="required"), candidate_iaca_der=root, independently_pinned_sha256="0" * 64
    )["status"] == "anchor_fingerprint_mismatch"


def test_pinned_leaf_rejected():
    _, leaf, _ = _make_chain()
    assert _report(
        _profile(reader_auth="required"), candidate_iaca_der=leaf,
        independently_pinned_sha256=hashlib.sha256(leaf).hexdigest(),
    )["status"] == "invalid_anchor_ca_shape"


def test_candidate_root_shape_not_trust():
    root, _, _ = _make_chain()
    report = _report(
        _profile(reader_auth="required"), candidate_iaca_der=root,
        independently_pinned_sha256=hashlib.sha256(root).hexdigest(),
    )
    assert report["status"] == "candidate_profile_structurally_ready_not_verified", report
    assert report["anchor_ca_shape_valid"] is True


def _attempt_args(sample, attempt):
    args, key = sample
    args = dict(args)
    args.pop("transcript_bytes")
    args["device_signature_bytes"] = _sign(
        key, _payload(attempt.transcript_for_lab_holder(), args["namespaces_bytes"]), detached=True
    )
    return args


def test_session_consumed_after_success(sample):  # noqa: F811
    attempt = SyntheticReaderAttempt()
    args = _attempt_args(sample, attempt)
    assert attempt.verify(**args)["status"] == "synthetic_device_auth_precheck_passed_not_identity"
    assert attempt.verify(**args)["status"] == "session_already_consumed"
    with pytest.raises(RuntimeError, match="session_already_consumed"):
        attempt.transcript_for_lab_holder()


def test_failed_attempt_consumed(sample):  # noqa: F811
    attempt = SyntheticReaderAttempt()
    args = _attempt_args(sample, attempt)
    bad = dict(args, device_signature_bytes=b"bad")
    assert attempt.verify(**bad)["synthetic_device_signature_valid"] is False
    assert attempt.verify(**args)["status"] == "session_already_consumed"


def test_distinct_attempts(sample):  # noqa: F811
    a, b = SyntheticReaderAttempt(), SyntheticReaderAttempt()
    assert a.transcript_for_lab_holder() != b.transcript_for_lab_holder()
    args = _attempt_args(sample, a)
    assert b.verify(**args)["status"] == "invalid_device_signature"
    assert a.verify(**args)["synthetic_device_signature_valid"] is True


def test_concurrent_duplicate_attempt(sample):  # noqa: F811
    attempt = SyntheticReaderAttempt()
    args = _attempt_args(sample, attempt)
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: attempt.verify(**args)["status"], range(2)))
    assert sorted(statuses) == [
        "session_already_consumed", "synthetic_device_auth_precheck_passed_not_identity"
    ]
