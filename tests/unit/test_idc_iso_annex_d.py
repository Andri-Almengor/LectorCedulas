"""QA22: published synthetic Annex D.5.1/D.5.3 known-answer vector.

Vector bytes transcribed from the Apache-2.0 Multipaz TestVectors.kt
(blob 91af0ce314b8e37a008b3463049c048e3130deb9; AOSP copyright 2022).
https://github.com/openwallet-foundation/multipaz/blob/main/multipaz/src/commonTest/kotlin/org/multipaz/mdoc/TestVectors.kt
Intermediate expected values independently cross-checked with ISO/IEC
18013-5:2021 Annex D. Never use these public test keys for live sessions.
No real credential, certificate or personal data is included.
"""
import hashlib
import hmac
from types import SimpleNamespace

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from tools.idc_diagnostic.device_mac_precheck import DOC, inspect_mac_consistency

TRANSCRIPT = bytes.fromhex(
    "d81859024183d8185858a20063312e30018201d818584ba4010220012158205a88d182bce5f42efa"
    "59943f33359d2e8a968ff289d93e5fa444b624343167fe225820b16e8cf858ddc7690407ba61d4c3"
    "38237a8cfcf3de6aa672fc60a557aa32fc67d818584ba40102200121582060e3392385041f514030"
    "51f2415531cb56dd3f999c71687013aac6768bc8187e225820e58deb8fdbe907f7dd5368245551a3"
    "4796f7d2215c440c339bb0f7b67beccdfa8258c391020f487315d10209616301013001046d646f63"
    "1a200c016170706c69636174696f6e2f766e642e626c7565746f6f74682e6c652e6f6f6230081b28"
    "128b37282801021c015c1e580469736f2e6f72673a31383031333a646576696365656e676167656d"
    "656e746d646f63a20063312e30018201d818584ba4010220012158205a88d182bce5f42efa59943f"
    "33359d2e8a968ff289d93e5fa444b624343167fe225820b16e8cf858ddc7690407ba61d4c338237a"
    "8cfcf3de6aa672fc60a557aa32fc6758cd9102254872159102026372010211020461630101300011"
    "0206616301036e6663005102046163010157001a201e016170706c69636174696f6e2f766e642e62"
    "6c7565746f6f74682e6c652e6f6f6230081b28078080bf2801021c021107c832fff6d26fa0beb34d"
    "fcd555d4823a1c11010369736f2e6f72673a31383031333a6e66636e6663015a172b016170706c69"
    "636174696f6e2f766e642e7766612e6e616e57030101032302001324fec9a70b97ac9684a4e32617"
    "6ef5b981c5e8533e5f00298cfccbc35e700a6b020414"
)

READER_D = bytes.fromhex(
    "de3b4b9e5f72dd9b58406ae3091434da48a6f9fd010d88fcb0958e2cebec947c"
)

DEVICE_X = bytes.fromhex(
    "96313d6c63e24e3372742bfdb1a33ba2c897dcd68ab8c753e4fbd48dca6b7f9a"
)

DEVICE_Y = bytes.fromhex(
    "1fb3269edd418857de1b39a4e4a44b92fa484caa722c228288f01d0c03a2c3d6"
)

EXPECTED_SHARED = bytes.fromhex(
    "78d98a86fbbb82895874bfafcc161ba69f9b77662172c74b3b0d4643276cf991"
)

EXPECTED_EMAC = bytes.fromhex(
    "dc2b9566fdaaae3c06baa40993cd0451aeba15e7677ef5305f6531f3533c35dd"
)

EXPECTED_MAC = bytes.fromhex(
    "e99521a85ad7891b806a07f8b5388a332d92c189a7bf293ee1f543405ae6824d"
)

def _reader():
    return ec.derive_private_key(int.from_bytes(READER_D, "big"), ec.SECP256R1())


def _fixture():
    material = SimpleNamespace(session_transcript=TRANSCRIPT, reader_key=_reader())
    mso = {
        "version": "1.0", "docType": DOC,
        "deviceKeyInfo": {"deviceKey": {1: 2, -1: 1, -2: DEVICE_X, -3: DEVICE_Y}},
    }
    response = {
        "version": "1.0", "status": 0, "documents": [{
            "docType": DOC,
            # Deliberately unsigned scaffold: not an authentic issuer object.
            "issuerSigned": {"issuerAuth": [
                b"", {}, cbor2.dumps(cbor2.CBORTag(24, cbor2.dumps(mso))), b"",
            ]},
            "deviceSigned": {
                "nameSpaces": cbor2.CBORTag(24, b"\xa0"),
                "deviceAuth": {"deviceMac": [bytes.fromhex("a10105"), {}, None, EXPECTED_MAC]},
            },
        }],
    }
    return response, material


def test_published_ecdh_and_hkdf():
    public = ec.EllipticCurvePublicNumbers(
        int.from_bytes(DEVICE_X, "big"), int.from_bytes(DEVICE_Y, "big"), ec.SECP256R1()
    ).public_key()
    shared = _reader().exchange(ec.ECDH(), public)
    assert shared == EXPECTED_SHARED
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=hashlib.sha256(TRANSCRIPT).digest(),
        info=b"EMacKey",
    ).derive(shared)
    assert key == EXPECTED_EMAC


def test_published_tag_from_independent_byte_framing():
    # Annex D uses NFC handover, not QR. The MAC is transport-independent
    # and must bind to the precise transcript from the published example.
    assert TRANSCRIPT[:5] == bytes.fromhex("d818590241")
    payload = (
        bytes.fromhex("d818590271847444657669636541757468656e7469636174696f6e")
        + TRANSCRIPT[5:] + bytes.fromhex("756f72672e69736f2e31383031332e352e312e6d444cd81841a0")
    )
    structure = bytes.fromhex("84644d41433043a1010540590276") + payload
    assert hmac.digest(EXPECTED_EMAC, structure, "sha256") == EXPECTED_MAC


def test_repo_precheck_matches_annex_d():
    response, material = _fixture()
    result = inspect_mac_consistency(response, material)
    assert result["mdl_mac_consistency_checked"] is True, result
    assert result["mdl_mac_matches_untrusted_mso_key"] is True, result
    assert result["mdl_mac_nonstandard_payload_probe_checked"] is False


@pytest.mark.parametrize("mode", ["tag", "reader_key"])
def test_repo_precheck_rejects_changes(mode):
    response, material = _fixture()
    if mode == "tag":
        mac = response["documents"][0]["deviceSigned"]["deviceAuth"]["deviceMac"]
        mac[3] = bytes([EXPECTED_MAC[0] ^ 1]) + EXPECTED_MAC[1:]
    else:
        material.reader_key = ec.generate_private_key(ec.SECP256R1())
    result = inspect_mac_consistency(response, material)
    assert result["mdl_mac_consistency_checked"] is True, result
    assert result["mdl_mac_matches_untrusted_mso_key"] is False


def test_attached_known_payload_is_not_standard_mac():
    response, material = _fixture()
    payload = (
        bytes.fromhex("d818590271847444657669636541757468656e7469636174696f6e")
        + TRANSCRIPT[5:] + bytes.fromhex("756f72672e69736f2e31383031332e352e312e6d444cd81841a0")
    )
    response["documents"][0]["deviceSigned"]["deviceAuth"]["deviceMac"][2] = payload
    result = inspect_mac_consistency(response, material)
    assert result["mdl_mac_payload_matches_expected"] is True
    assert result["mdl_mac_nonstandard_expected_tag_matches"] is True
    assert result["mdl_mac_consistency_checked"] is False
    assert result["mdl_mac_matches_untrusted_mso_key"] is False
