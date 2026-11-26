import json
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import cbor2
import pytest

from tools.idc_diagnostic import photoid_candidate as probe


def test_request_has_only_issuing_country():
    request = cbor2.loads(probe.candidate_request())
    item = cbor2.loads(request["docRequests"][0]["itemsRequest"].value)
    assert item == {
        "docType": "org.iso.23220.photoid.1",
        "nameSpaces": {"org.iso.23220.1": {"issuing_country": False}},
    }
    assert "readerAuth" not in request["docRequests"][0]


def test_consent_required(monkeypatch):
    transport = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(probe, "_get_transport_options", transport)
    for consent, allow in [(False, True), (True, False)]:
        assert probe.probe_candidate(b"test", consent=consent, allow_candidate=allow)[
            "status"
        ] == "consent_and_candidate_permission_required"
    transport.assert_not_called()


@pytest.mark.parametrize("count, errors, authenticated, expected", [
    ("one", False, True, "candidate_document_observed_not_verified"),
    ("absent", True, True, "candidate_document_error_not_verified"),
    ("one", False, False, "no_authenticated_candidate_response"),
    ("multiple", False, True, "candidate_response_inconclusive"),
])
def test_result_is_categorical(monkeypatch, count, errors, authenticated, expected):
    monkeypatch.setattr(probe, "_get_transport_options", lambda *_a, **_k: (
        "ok", True, False, UUID(int=1)
    ))
    monkeypatch.setattr(probe, "prepare_reader_session", lambda _: object())
    monkeypatch.setattr(probe, "build_session_establishment", lambda *_: b"packet")
    monkeypatch.setattr(probe, "_ble_exchange", AsyncMock(return_value={
        "encrypted_reply_authenticated": authenticated,
        "response_status_code": 0,
        "response_document_count_category": count,
        "response_document_errors_present": errors,
        "response_document_error_category": "data_not_returned" if errors else "absent",
        "response_structure_acceptable": True,
        "unexpected": "PRIVATE_TEST_VALUE",
    }))
    result = probe.probe_candidate(b"test", consent=True, allow_candidate=True)
    assert result["status"] == expected, result
    assert result["response_document_error_category"] == (
        ("data_not_returned" if errors else "absent") if authenticated else "unavailable"
    )
    assert result["verified_identity"] is False
    assert result["candidate_is_confirmed_idc_profile"] is False
    assert "PRIVATE_TEST_VALUE" not in json.dumps(result)


def test_mdl_request_has_only_country():
    request = cbor2.loads(probe.candidate_request(profile="mdl"))
    item = cbor2.loads(request["docRequests"][0]["itemsRequest"].value)
    assert item == {
        "docType": "org.iso.18013.5.1.mDL",
        "nameSpaces": {"org.iso.18013.5.1": {"issuing_country": False}},
    }
    assert "readerAuth" not in request["docRequests"][0]


def test_arbitrary_profile_rejected_before_ble(monkeypatch):
    transport = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(probe, "_get_transport_options", transport)
    result = probe.probe_candidate(b"test", consent=True, allow_candidate=True, profile="unknown")
    assert result["status"] == "unsupported_public_profile"
    transport.assert_not_called()


def test_mdl_probe_report(monkeypatch):
    monkeypatch.setattr(probe, "_get_transport_options", lambda *_a, **_k: (
        "ok", True, False, UUID(int=1)
    ))
    monkeypatch.setattr(probe, "prepare_reader_session", lambda _: object())
    def check_packet(_material, _cipher, request):
        assert request == probe.candidate_request(profile="mdl")
        return b"packet"
    monkeypatch.setattr(probe, "build_session_establishment", check_packet)
    monkeypatch.setattr(probe, "_ble_exchange", AsyncMock(return_value={
        "encrypted_reply_authenticated": True,
        "response_status_code": 0,
        "response_document_count_category": "absent",
        "response_document_errors_present": True,
        "response_document_error_category": "data_not_returned",
    }))
    result = probe.probe_candidate(b"test", consent=True, allow_candidate=True, profile="mdl")
    assert result["public_profile_tested"] == "mdl"
    assert result["purpose"] == "public_mdl_candidate_probe_only"
    assert result["status"] == "candidate_document_error_not_verified"
    assert result["verified_identity"] is False


@pytest.mark.parametrize("flags", [[], ["--allow-photoid-candidate", "--allow-mdl-candidate"]])
def test_cli_requires_one_profile_permission(monkeypatch, flags):
    capture = Mock(side_effect=AssertionError("must not capture"))
    monkeypatch.setattr(probe, "capture_serial", capture)
    with pytest.raises(SystemExit):
        probe.main(["--port", "COM5", "--consent", *flags])
    capture.assert_not_called()
