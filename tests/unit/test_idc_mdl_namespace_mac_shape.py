"""QA20: diagnóstico de namespaces y forma MAC/MSO sin valores."""
import json

import cbor2
import pytest

from tools.idc_diagnostic.mdl_response_shape import DOC, NS, inspect_mdl_shape
from test_idc_mdl_response_shape import _item, _response


@pytest.mark.parametrize("spaces, present, empty, other, additional", [
    (None, False, False, False, False),
    ({}, True, True, False, False),
    ({"private.namespace": [_item()]}, True, False, True, True),
    ({NS: []}, True, False, False, False),
])
def test_issuer_namespace_states(spaces, present, empty, other, additional):
    response = _response()
    issuer = response["documents"][0]["issuerSigned"]
    if spaces is None:
        issuer.pop("nameSpaces")
    else:
        issuer["nameSpaces"] = spaces
    report = inspect_mdl_shape(response)
    assert report["mdl_issuer_namespaces_present"] is present
    assert report["mdl_issuer_namespaces_empty"] is empty
    assert report["mdl_issuer_other_namespace_present"] is other
    assert report["mdl_additional_issuer_items_present"] is additional
    assert report["mdl_issuer_requested_namespace_empty"] is (spaces == {NS: []})
    assert "private.namespace" not in json.dumps(report)


def test_mso_and_mac_shape_not_verification():
    response = _response()
    doc = response["documents"][0]
    mso = {
        "docType": DOC,
        "valueDigests": {"private.namespace": {0: b"x" * 32}},
        "deviceKeyInfo": {"deviceKey": {1: 2, -1: 1, -2: b"x" * 32, -3: b"y" * 32}},
    }
    payload = cbor2.dumps(cbor2.CBORTag(24, cbor2.dumps(mso)))
    doc["issuerSigned"]["issuerAuth"] = cbor2.CBORTag(18, [b"", {}, payload, b"fake"])
    doc["deviceSigned"] = {
        "nameSpaces": cbor2.CBORTag(24, cbor2.dumps({})),
        "deviceAuth": {"deviceMac": cbor2.CBORTag(17, [
            cbor2.dumps({1: 5}), {}, None, b"z" * 32,
        ])},
    }
    report = inspect_mdl_shape(response)
    for key in (
        "mdl_mso_decodable", "mdl_mso_doc_type_matches", "mdl_mso_other_digest_namespace_present",
        "mdl_mso_device_key_p256_shape", "mdl_mac_hmac256_shape",
        "mdl_device_namespaces_present", "mdl_device_namespaces_empty",
    ):
        assert report[key] is True, report
    assert report["mdl_mso_requested_digest_namespace_present"] is False
    assert "private.namespace" not in json.dumps(report)


@pytest.mark.parametrize("algorithm, tag", [(4, b"z" * 32), (5, b"z" * 8), (True, b"z" * 32)])
def test_wrong_mac_shape(algorithm, tag):
    response = _response()
    response["documents"][0]["deviceSigned"]["deviceAuth"] = {
        "deviceMac": [cbor2.dumps({1: algorithm}), {}, None, tag],
    }
    assert inspect_mdl_shape(response)["mdl_mac_hmac256_shape"] is False


def test_device_namespace_and_element_error_flags():
    response = _response()
    doc = response["documents"][0]
    doc["errors"] = {"private.namespace": {"private.field": 0}}
    doc["deviceSigned"]["nameSpaces"] = cbor2.CBORTag(24, cbor2.dumps({
        NS: {}, "private.namespace": {"private.field": "PRIVATE"},
    }))
    report = inspect_mdl_shape(response)
    assert report["mdl_document_item_errors_present"] is True
    assert report["mdl_device_requested_namespace_present"] is True
    assert report["mdl_device_other_namespace_present"] is True
    assert report["mdl_device_namespaces_empty"] is False
    assert "PRIVATE" not in json.dumps(report)
    assert "private.field" not in json.dumps(report)


def test_invalid_mso_and_device_namespaces_are_not_accepted():
    response = _response()
    doc = response["documents"][0]
    doc["issuerSigned"]["issuerAuth"] = [b"", {}, b"invalid", b"fake"]
    doc["deviceSigned"]["nameSpaces"] = cbor2.CBORTag(24, b"invalid")
    report = inspect_mdl_shape(response)
    assert report["mdl_mso_decodable"] is False
    assert report["mdl_device_namespaces_present"] is False
