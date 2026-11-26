"""Guía de verificación IDC con el aplicativo oficial (proceso externo).

Esta guía no toca BLE, QR, identidad, formularios ni archivos: el resultado
de verificación sólo existe en el verificador del TSE, no en LectorCedulas.
"""
from __future__ import annotations

OFFICIAL_TSE_IDC_URL = "https://www.tse.go.cr/idc/"
OFFICIAL_VERIFIER_NAME = "Verificador IDC del TSE (aplicación externa)"
OFFICIAL_GUIDE_STEPS: tuple[str, ...] = (
    "1. Solicite al visitante que abra Identidad Digital CR y genere un QR nuevo.",
    "2. Use el Verificador IDC oficial en Windows, Android o iOS. "
    "Espere su resultado y revise los datos que haya autorizado el titular.",
    "3. Compruebe presencialmente que la persona coincida con la "
    "identificación mostrada. Si no puede verificar, no indique que fue validada.",
    "4. Solo si el verificador oficial confirma y el procedimiento lo autoriza, "
    "registre manualmente en el formulario de visitas los datos mínimos "
    "necesarios (por ejemplo, nombre, apellido y cédula).",
)
OFFICIAL_GUIDE_PRIVACY = (
    "No tome ni conserve fotografías, capturas de pantalla o copias del QR "
    "de la IDC. No retenga el teléfono del visitante. Solicite únicamente "
    "los datos personales necesarios para el trámite."
)
OFFICIAL_GUIDE_NOTICE = (
    "LectorCedulas NO verifica criptográficamente la IDC ni recibe "
    "resultados del Verificador oficial. Esta ventana es solo una guía "
    "para un procedimiento manual independiente."
)
