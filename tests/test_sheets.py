"""Чтение и проверка данных из Google Sheets, кеш и запасной вариант."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

import calc
import sheets
from helpers import raw_data, rules_from, row_of

FALLBACK = Path(__file__).parent.parent / "data" / "fallback.json"


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setattr(sheets, "_last_good", None)


def parse_error(raw):
    with pytest.raises(sheets.DataError) as err:
        sheets.parse_rules(raw)
    return str(err.value)


# ---- нормальные данные -------------------------------------------------------
def test_fallback_file_is_valid_and_matches_test_data():
    rules = sheets.parse_rules(json.loads(FALLBACK.read_text(encoding="utf-8")))
    assert len(rules.tariffs) == 10
    assert json.loads(FALLBACK.read_text(encoding="utf-8")) == raw_data()


def test_different_cell_formats_give_same_result():
    raw = raw_data()
    row_of(raw, "Тарифы", "Salom Pro")[2] = "80 000"
    row_of(raw, "Тарифы", "Farzand")[2] = "55\u00a0000,00"
    row_of(raw, "Тарифы", "Salom Pro")[5] = "Да"
    rates = raw["Ставки"]
    rates[1][4:7] = ["65%", "65", "0,5"]            # проценты, число, доля
    raw["Тарифы"][0][0] = " тариф "                 # регистр и пробелы в заголовке
    a = calc.calculate(rules_from(raw), "TOP", "MBR", True, {"Salom Pro": 5, "Farzand": 2})
    b = calc.calculate(rules_from(), "TOP", "MBR", True, {"Salom Pro": 5, "Farzand": 2})
    assert a.month_totals == b.month_totals


def test_checkbox_booleans_and_inactive_tariffs():
    raw = raw_data()
    row_of(raw, "Тарифы", "Balance")[6] = False      # флажок «Активен» снят
    row_of(raw, "Тарифы", "Mini Voice")[7] = 99      # порядок
    names = [t.name for t in sheets.parse_rules(raw).tariffs]
    assert "Balance" not in names and names[-1] == "Mini Voice"


def test_blank_third_month_rate_means_not_paid_but_blank_second_is_error():
    raw = raw_data()
    raw["Ставки"][1][6] = ""
    assert sheets.parse_rules(raw).rates[0].months[2] == Decimal(0)
    raw["Ставки"][1][5] = ""
    assert "Ставка 2 мес" in parse_error(raw)


# ---- ошибки в данных ---------------------------------------------------------
@pytest.mark.parametrize("mutate,fragment", [
    (lambda r: r["Тарифы"][0].remove("Цена с НДС"), "нет колонки «Цена с НДС»"),
    (lambda r: r.pop("Ставки"), "Ставки"),
    (lambda r: r["Тарифы"].append(list(r["Тарифы"][1])), "указан дважды"),
    (lambda r: row_of(r, "Тарифы", "Salom Pro").__setitem__(2, "abc"), "не число"),
    (lambda r: row_of(r, "Тарифы", "Salom Pro").__setitem__(2, -5), "отрицательными"),
    (lambda r: row_of(r, "Тарифы", "Salom Pro").__setitem__(2, 0), "больше 0"),
    (lambda r: row_of(r, "Тарифы", "Salom Pro").__setitem__(5, "возможно"), "«да» или «нет»"),
    (lambda r: row_of(r, "Тарифы", "Bonus Salom Pro").__setitem__(3, "Нет такого"), "не найден"),
    (lambda r: row_of(r, "Тарифы", "Salom Pro").__setitem__(6, "нет"), "отключён"),
    (lambda r: row_of(r, "Тарифы", "Bonus Salom Pro").__setitem__(4, ""), "фиксированное"),
    (lambda r: r["Ставки"][1].__setitem__(1, "VIP"), "нет в листе"),
    (lambda r: r["Ставки"][1].__setitem__(4, 150), "вне диапазона"),
    (lambda r: r["Ставки"][1].__setitem__(4, "abc"), "не число"),
    (lambda r: r["Ставки"][1].__setitem__(2, "возможно"), "«План»"),
    (lambda r: r["Настройки"].pop(1), "не указан НДС"),
    (lambda r: r["Настройки"].append(["Категория", "top", "Дубль", "", ""]), "уже есть"),
    (lambda r: r["Настройки"].append(["Что-то", "", "", "", ""]), "неизвестный вид"),
])
def test_invalid_data_is_rejected(mutate, fragment):
    raw = raw_data()
    mutate(raw)
    assert fragment in parse_error(raw)


def test_missing_rate_combination_is_rejected():
    raw = raw_data()
    raw["Ставки"] = [r for r in raw["Ставки"] if not (r[0] == "обычный" and r[3] == "M")]
    assert "Нет ставки" in parse_error(raw)


def test_ambiguous_rates_are_rejected():
    raw = raw_data()
    raw["Ставки"].append(["BUNDLE", "TOP", "да", "*", 0.7, 0.7, 0.5])     # дубль строки Топ
    assert "Несколько" in parse_error(raw)


def test_empty_sheet_and_no_active_tariffs():
    raw = raw_data()
    raw["Настройки"] = []
    assert "пуст" in parse_error(raw)
    raw = raw_data()
    for row in raw["Тарифы"][1:]:
        row[6] = "нет"
    assert "нет ни одного активного" in parse_error(raw)


# ---- загрузка: таблица -> кеш -> запасной файл -------------------------------
def test_uses_sheets_when_available():
    result = sheets.load_rules(lambda: raw_data(), FALLBACK)
    assert result.source == "sheets" and result.error == ""


def test_without_connection_uses_fallback_file():
    result = sheets.load_rules(None, FALLBACK)
    assert result.source == "fallback"


def test_uses_last_good_data_when_sheets_fails():
    good = sheets.load_rules(lambda: raw_data(), FALLBACK)

    def broken():
        raise TimeoutError("нет связи")

    result = sheets.load_rules(broken, FALLBACK)
    assert result.source == "cache" and result.rules is good.rules
    assert "TimeoutError" in result.error


def test_uses_last_good_data_when_table_becomes_invalid():
    sheets.load_rules(lambda: raw_data(), FALLBACK)
    bad = raw_data()
    bad["Ставки"][1][4] = 150
    result = sheets.load_rules(lambda: bad, FALLBACK)
    assert result.source == "cache" and "вне диапазона" in result.error


def test_first_start_with_broken_sheets_uses_fallback_file():
    def broken():
        raise ConnectionError("403")

    assert sheets.load_rules(broken, FALLBACK).source == "fallback"


def test_broken_fallback_raises(tmp_path):
    bad = tmp_path / "fallback.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(sheets.DataError):
        sheets.load_rules(None, bad)


def test_fetch_raw_reads_three_sheets_read_only(monkeypatch):
    import gspread
    from gspread.utils import ValueRenderOption

    calls = {}

    class FakeSheet:
        def __init__(self, name):
            self.name = name

        def get_all_values(self, value_render_option=None):
            calls["render"] = value_render_option
            return [[self.name]]

    class FakeBook:
        def worksheet(self, name):
            return FakeSheet(name)

    class FakeClient:
        def set_timeout(self, seconds):
            calls["timeout"] = seconds

        def open_by_key(self, key):
            calls["key"] = key
            return FakeBook()

    def fake_factory(info, scopes):
        calls["scopes"] = scopes
        return FakeClient()

    monkeypatch.setattr(gspread, "service_account_from_dict", fake_factory)
    raw = sheets.fetch_raw({"client_email": "x"}, "SHEET_ID")
    assert set(raw) == set(sheets.SHEET_NAMES)
    assert calls["scopes"] == [sheets.READONLY_SCOPE]
    assert calls["key"] == "SHEET_ID" and calls["timeout"] == sheets.TIMEOUT_SECONDS
    assert calls["render"] == ValueRenderOption.unformatted
