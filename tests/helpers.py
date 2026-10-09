import copy
import json
from pathlib import Path

import sheets

RULES_FILE = Path(__file__).parent / "excel_rules.json"


def raw_data():
    """Исходные правила (как в CALC.xlsx) в виде «сырых» листов — можно менять в тестах."""
    return copy.deepcopy(json.loads(RULES_FILE.read_text(encoding="utf-8")))


def rules_from(raw=None):
    return sheets.parse_rules(raw if raw is not None else raw_data())


def row_of(raw, sheet, first_cell):
    return next(r for r in raw[sheet] if r[0] == first_cell)
