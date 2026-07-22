"""
LECCIÓN 01 — Anatomía de un test: assert y parametrize.

Módulo bajo prueba: tiddl/core/utils/sanitize.py
    sanitize_string() elimina caracteres prohibidos en nombres de archivo
    (Tidal a veces devuelve títulos con `/`, `:`, `?`...). Si esta función
    falla, tiddl crearía rutas inválidas en Windows/NAS.

Reglas básicas de pytest:
  1. Los archivos se llaman `test_*.py` y las funciones `test_*` — pytest
     los descubre solo, sin registrar nada.
  2. No hay clases ni métodos especiales: un `assert` normal de Python basta.
     Si el assert falla, pytest muestra los valores de cada lado.
"""

import pytest

from tiddl.core.utils.sanitize import sanitize_string


def test_elimina_slash():
    # El caso más simple posible: una entrada, una salida esperada.
    assert sanitize_string("AC/DC") == "ACDC"


def test_texto_limpio_queda_igual():
    assert sanitize_string("Hola Mundo") == "Hola Mundo"


# @pytest.mark.parametrize convierte UNA función en N tests independientes:
# cada tupla (entrada, esperado) aparece como un test separado en el reporte.
# Es la herramienta número 1 para funciones puras.
@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ('Track: "Live" Version?', "Track Live Version"),
        ("<track>|<video>", "trackvideo"),
        ("C:\\Users\\music", "CUsersmusic"),
        ("What/Ever: Yes?", "WhatEver Yes"),
        ("***", ""),  # solo caracteres prohibidos -> string vacío
        ("", ""),
    ],
)
def test_elimina_caracteres_prohibidos(entrada: str, esperado: str):
    assert sanitize_string(entrada) == esperado


def test_es_idempotente():
    # Propiedad general: sanitizar dos veces = sanitizar una vez.
    # Pensar en PROPIEDADES (no solo ejemplos) atrapa bugs inesperados.
    sucio = 'a/b:c"d*e?f<g>h|i'
    una_vez = sanitize_string(sucio)
    assert sanitize_string(una_vez) == una_vez
