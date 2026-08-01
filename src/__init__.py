"""Postador automatico.

Os nomes dos videos tem emoji, e o console do Windows usa cp1252 por padrao:
sem isto, um simples print do nome do arquivo derruba a execucao com
UnicodeEncodeError. No Linux (GitHub Actions) ja e UTF-8 e nada muda.
"""
import sys

for _fluxo in (sys.stdout, sys.stderr):
    try:
        _fluxo.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
