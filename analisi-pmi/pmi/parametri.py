"""Parametri: valori predefiniti nel codice, sovrascritti da config.yaml se presente."""
from __future__ import annotations

import copy
from pathlib import Path

try:
    import yaml
except ImportError:  # PyYAML è nei requisiti; senza, valgono i predefiniti
    yaml = None

RADICE = Path(__file__).resolve().parent.parent
FILE_CONFIG = RADICE / "config.yaml"

PREDEFINITI = {
    "server": {"porta": 8800, "ollama": {"attivo": True, "indirizzo": "http://127.0.0.1:11434",
                                         "modello": "gemma3:12b", "timeout": 600, "stile": "../stile_alberto.md"}},
    "soglie": {
        "liquidita_corrente": {"verde": 1.2, "giallo": 1.0},
        "liquidita_immediata": {"verde": 1.0, "giallo": 0.7},
        "indipendenza_finanziaria": {"verde": 0.30, "giallo": 0.15},
        "pfn_ebitda": {"verde": 3.0, "giallo": 5.0},
        "pfn_pn": {"verde": 1.0, "giallo": 2.0},
        "copertura_oneri": {"verde": 5.0, "giallo": 2.0},
        "oneri_su_ricavi": {"verde": 0.02, "giallo": 0.04},
        "ebitda_margin": {"verde": 0.10, "giallo": 0.05},
        "ros": {"verde": 0.05, "giallo": 0.0},
        "roe": {"verde": 0.08, "giallo": 0.0},
        "dso": {"verde": 60, "giallo": 90},
        "tfr_su_liquidita": {"verde": 0.5, "giallo": 1.0},
        "altman_z": {"verde": 2.6, "giallo": 1.1},
    },
    "tfr": {"inflazione": 0.02, "crescita_retribuzioni": 0.02, "turnover": 0.05, "anticipi": 0.02,
            "quota_anticipo": 0.70, "eta_pensione": 67, "orizzonte": 10, "rendimento_polizza": 0.025,
            "stress_persone": 3, "anni_medi_pensione": 15},
    "tfm": {"percentuale": 0.0741, "rendimento_polizza": 0.025, "ires": 0.24, "aliquota_marginale": 0.45,
            "aliquota_separata": 0.33, "contributi_gs": 0.35, "contributi_tfm": 0.0},
    "rischi": {"anni_sostituzione_persona_chiave": 2, "multiplo_ebitda_valutazione": 5},
    "scadenze": {"giorni_approvazione_bilancio": 120, "giorni_preavviso": 60},
}


def _unisci(base: dict, sopra: dict) -> dict:
    for k, v in (sopra or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _unisci(base[k], v)
        else:
            base[k] = v
    return base


def carica() -> dict:
    p = copy.deepcopy(PREDEFINITI)
    if yaml is not None and FILE_CONFIG.exists():
        with open(FILE_CONFIG, encoding="utf-8") as f:
            _unisci(p, yaml.safe_load(f) or {})
    return p
