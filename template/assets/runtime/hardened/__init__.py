"""Servicios endurecidos del Lector de Cédulas DMS.

Los módulos de este paquete no instalan monkey patches al importarse.
"""

from .version import PRODUCT_ID, PRODUCT_NAME, VERSION

__all__ = ["PRODUCT_ID", "PRODUCT_NAME", "VERSION"]
