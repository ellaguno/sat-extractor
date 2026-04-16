"""Módulo fiscal: cálculo de impuestos y clasificación de deducciones."""

from .impuestos import calcular_impuestos_mensuales
from .clasificador import ClasificadorDeducciones

__all__ = ["calcular_impuestos_mensuales", "ClasificadorDeducciones"]
