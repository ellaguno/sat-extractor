"""Módulo fiscal: cálculo de impuestos y clasificación de deducciones."""

from .impuestos import calcular_impuestos_mensuales, isr_label
from .clasificador import ClasificadorDeducciones

__all__ = ["calcular_impuestos_mensuales", "isr_label", "ClasificadorDeducciones"]
