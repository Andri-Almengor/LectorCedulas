from __future__ import annotations

import pytest

from assets.runtime.hardened.url_security import UrlValidationError, validate_https_url


def test_exact_official_host_is_accepted():
    result = validate_https_url("https://www.consulta.tse.go.cr/consultacedula/Cedula?cedula=123456789", allowed_hosts={"www.consulta.tse.go.cr"})
    assert result.hostname == "www.consulta.tse.go.cr"


@pytest.mark.parametrize("url", ["http://www.consulta.tse.go.cr/x", "https://www.consulta.tse.go.cr.evil.test/x", "https://evil.test/?next=www.consulta.tse.go.cr", "https://user:pass@www.consulta.tse.go.cr/x", "https://www.consulta.tse.go.cr:444/x"])
def test_malicious_or_similar_urls_are_rejected(url):
    with pytest.raises(UrlValidationError):
        validate_https_url(url, allowed_hosts={"www.consulta.tse.go.cr"})
