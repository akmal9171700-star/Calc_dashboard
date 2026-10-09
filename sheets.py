"""Данные из Google Sheets: чтение, проверка, запасной вариант.

parse_rules() — чистая функция (без сети): её легко проверять тестами.
load_rules()  — читает таблицу и при любой проблеме берёт последние
                корректные данные, а если их нет — data/fallback.json.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from calc import (PLAN_NO, PLAN_YES, WILDCARD, Option, RateRow, Rules,
                  RulesError, Tariff, find_rate)

log = logging.getLogger(__name__)

SHEET_TARIFFS = "Тарифы"
SHEET_RATES = "Ставки"
SHEET_SETTINGS = "Настройки"
SHEET_NAMES = (SHEET_TARIFFS, SHEET_RATES, SHEET_SETTINGS)
READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
TIMEOUT_SECONDS = 15

COLS_TARIFFS = ["Тариф", "Тип", "Цена с НДС", "Основной тариф",
                "Фиксированное вознаграждение", "3-й месяц", "Активен", "Порядок"]
COLS_RATES = ["Тип", "Категория", "План", "Регион",
              "Ставка 1 мес", "Ставка 2 мес", "Ставка 3 мес"]
COLS_SETTINGS = ["Вид", "Код", "Рус", "Узб", "Значение"]

_SPACES = re.compile(r"[\s\u00a0\u202f]+")
_YES = {"да", "yes", "true", "1", "y"}
_NO = {"нет", "no", "false", "0", "n"}


class DataError(ValueError):
    """Данные в таблице некорректны (сообщение — для администратора)."""


# --------------------------------------------------------------------------
# Разбор ячеек
# --------------------------------------------------------------------------
def _cell_text(cell: Any) -> str:
    if cell is None:
        return ""
    if isinstance(cell, bool):                      # флажок в Google Sheets
        return "да" if cell else "нет"
    if isinstance(cell, (int, float)):              # число без локальных разделителей
        return format(Decimal(str(cell)), "f")
    return str(cell).strip()


def _number(text: str, where: str) -> Decimal:
    cleaned = _SPACES.sub("", text).replace(",", ".")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise DataError(f"{where}: «{text}» — не число") from None
    if not value.is_finite():
        raise DataError(f"{where}: «{text}» — не число")
    return value


def _percent(text: str, where: str) -> Decimal:
    """Ставка: «65%», «65» (проценты) или «0,65» (доля) -> доля 0,65."""
    cleaned = text.strip()
    if cleaned.endswith("%"):
        value = _number(cleaned[:-1], where)
        if not 0 <= value <= 100:
            raise DataError(f"{where}: ставка «{text}» вне диапазона 0–100 %")
        return value / 100
    value = _number(cleaned, where)
    if 0 <= value <= 1:
        return value
    if 1 < value <= 100:
        return value / 100
    raise DataError(f"{where}: ставка «{text}» вне диапазона 0–100 %")


def _flag(text: str, where: str) -> bool:
    key = text.strip().casefold()
    if key in _YES:
        return True
    if key in _NO:
        return False
    raise DataError(f"{where}: ожидалось «да» или «нет», найдено «{text}»")


def _rows(raw: dict[str, list[list[Any]]], sheet: str,
          columns: list[str]) -> list[tuple[str, dict[str, str]]]:
    values = raw.get(sheet)
    if not values:
        raise DataError(f"Лист «{sheet}» пуст или не найден")
    header = [_cell_text(c).casefold() for c in values[0]]
    index: dict[str, int] = {}
    for column in columns:
        if column.casefold() not in header:
            raise DataError(f"Лист «{sheet}»: нет колонки «{column}»")
        index[column] = header.index(column.casefold())
    rows = []
    for number, row in enumerate(values[1:], start=2):
        cells = {col: _cell_text(row[i]) if i < len(row) else "" for col, i in index.items()}
        if any(cells.values()):
            rows.append((f"Лист «{sheet}», строка {number}", cells))
    return rows


# --------------------------------------------------------------------------
# Разбор листов
# --------------------------------------------------------------------------
def _parse_settings(raw) -> tuple[Decimal, tuple[Option, ...], tuple[Option, ...]]:
    vat: Decimal | None = None
    categories: list[Option] = []
    regions: list[Option] = []
    for where, c in _rows(raw, SHEET_SETTINGS, COLS_SETTINGS):
        kind = c["Вид"].casefold()
        if kind == "ндс":
            if vat is not None:
                raise DataError(f"{where}: НДС указан дважды")
            vat = _number(c["Значение"], where)
            if not 0 <= vat < 100:
                raise DataError(f"{where}: НДС должен быть от 0 до 100")
        elif kind in ("категория", "регион"):
            code = c["Код"]
            if not code or code == WILDCARD:
                raise DataError(f"{where}: укажите код (не пустой и не «*»)")
            if not c["Рус"]:
                raise DataError(f"{where}: укажите русское название")
            target = categories if kind == "категория" else regions
            if code.casefold() in {o.code.casefold() for o in target}:
                raise DataError(f"{where}: код «{code}» уже есть")
            target.append(Option(code, c["Рус"], c["Узб"] or c["Рус"]))
        else:
            raise DataError(f"{where}: неизвестный вид «{c['Вид']}» (нужно НДС, Категория или Регион)")
    if vat is None:
        raise DataError(f"Лист «{SHEET_SETTINGS}»: не указан НДС")
    if not categories or not regions:
        raise DataError(f"Лист «{SHEET_SETTINGS}»: нужна хотя бы одна категория и один регион")
    return vat, tuple(categories), tuple(regions)


def _parse_tariffs(raw) -> tuple[Tariff, ...]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for where, c in _rows(raw, SHEET_TARIFFS, COLS_TARIFFS):
        name = c["Тариф"]
        if not name:
            raise DataError(f"{where}: не указано название тарифа")
        if name.casefold() in seen:
            raise DataError(f"{where}: тариф «{name}» указан дважды")
        seen.add(name.casefold())
        if not c["Тип"]:
            raise DataError(f"{where}: не указан тип тарифа")
        price = _number(c["Цена с НДС"] or "0", where)
        fixed = _number(c["Фиксированное вознаграждение"] or "0", where)
        if price < 0 or fixed < 0:
            raise DataError(f"{where}: цена и вознаграждение не могут быть отрицательными")
        main = c["Основной тариф"]
        if main and not c["Фиксированное вознаграждение"]:
            raise DataError(f"{where}: у Bonus-тарифа укажите фиксированное вознаграждение")
        if not main and price <= 0:
            raise DataError(f"{where}: цена тарифа «{name}» должна быть больше 0")
        order_text = c["Порядок"]
        if order_text:
            order_value = _number(order_text, where)
            if order_value != order_value.to_integral_value():
                raise DataError(f"{where}: порядок должен быть целым числом")
            order = int(order_value)
        else:
            order = len(records) + 1
        records.append({
            "where": where, "name": name, "kind": c["Тип"].casefold(), "price": price,
            "main": main, "fixed": fixed, "third": _flag(c["3-й месяц"] or "нет", where),
            "active": _flag(c["Активен"] or "да", where), "order": order,
        })

    by_name = {r["name"].casefold(): r for r in records}
    tariffs: list[Tariff] = []
    for r in records:
        if not r["active"]:
            continue
        main_name = ""
        if r["main"]:
            main = by_name.get(r["main"].casefold())
            if main is None:
                raise DataError(f"{r['where']}: основной тариф «{r['main']}» не найден")
            if main["main"]:
                raise DataError(f"{r['where']}: основной тариф «{r['main']}» сам является Bonus-тарифом")
            if not main["active"]:
                raise DataError(f"{r['where']}: основной тариф «{r['main']}» отключён, а Bonus включён")
            main_name = main["name"]
        tariffs.append(Tariff(r["name"], r["kind"], r["price"], main_name,
                              r["fixed"], r["third"], r["order"]))
    if not tariffs:
        raise DataError(f"Лист «{SHEET_TARIFFS}»: нет ни одного активного тарифа")
    return tuple(sorted(tariffs, key=lambda t: t.order))


def _parse_rates(raw, categories, regions) -> tuple[RateRow, ...]:
    cat_codes = {o.code.casefold(): o.code for o in categories}
    reg_codes = {o.code.casefold(): o.code for o in regions}

    def pick(text: str, codes: dict[str, str], what: str, where: str) -> str:
        if text == WILDCARD:
            return WILDCARD
        if text.casefold() in codes:
            return codes[text.casefold()]
        raise DataError(f"{where}: {what} «{text}» нет в листе «{SHEET_SETTINGS}» (для «любой» укажите *)")

    rows = []
    for where, c in _rows(raw, SHEET_RATES, COLS_RATES):
        if not c["Тип"]:
            raise DataError(f"{where}: не указан тип тарифа")
        plan_text = c["План"].casefold()
        plan = {"да": PLAN_YES, "нет": PLAN_NO, WILDCARD: WILDCARD}.get(plan_text)
        if plan is None:
            raise DataError(f"{where}: в колонке «План» нужно «да», «нет» или *")
        months = []
        for i, column in enumerate(("Ставка 1 мес", "Ставка 2 мес", "Ставка 3 мес")):
            if not c[column]:
                if i == 2:                              # нет ставки за 3-й месяц — не платим
                    months.append(Decimal(0))
                    continue
                raise DataError(f"{where}: не указана «{column}»")
            months.append(_percent(c[column], f"{where}, «{column}»"))
        rows.append(RateRow(
            kind=c["Тип"].casefold(),
            category=pick(c["Категория"], cat_codes, "категория", where),
            plan=plan,
            region=pick(c["Регион"], reg_codes, "регион", where),
            months=tuple(months),  # type: ignore[arg-type]
        ))
    if not rows:
        raise DataError(f"Лист «{SHEET_RATES}» не содержит ставок")
    return tuple(rows)


def parse_rules(raw: dict[str, list[list[Any]]]) -> Rules:
    """Собирает и проверяет правила; при проблеме — DataError."""
    vat, categories, regions = _parse_settings(raw)
    tariffs = _parse_tariffs(raw)
    rules = Rules(vat, tariffs, _parse_rates(raw, categories, regions), categories, regions)
    # Для каждого типа тарифа должна быть однозначная ставка в любой комбинации.
    for kind in sorted({t.kind for t in tariffs if not t.is_bonus}):
        for category in categories:
            for region in regions:
                for plan_met in (True, False):
                    try:
                        find_rate(rules, kind, category.code, plan_met, region.code)
                    except RulesError as exc:
                        raise DataError(f"Лист «{SHEET_RATES}»: {exc}") from None
    return rules


# --------------------------------------------------------------------------
# Чтение и запасной вариант
# --------------------------------------------------------------------------
def fetch_raw(credentials: dict, spreadsheet_id: str) -> dict[str, list[list[Any]]]:
    """Читает три листа (только чтение). Числа приходят как числа, без форматирования."""
    import gspread
    from gspread.utils import ValueRenderOption

    client = gspread.service_account_from_dict(credentials, scopes=[READONLY_SCOPE])
    client.set_timeout(TIMEOUT_SECONDS)
    book = client.open_by_key(spreadsheet_id)
    return {
        name: book.worksheet(name).get_all_values(
            value_render_option=ValueRenderOption.unformatted)
        for name in SHEET_NAMES
    }


@dataclass(frozen=True)
class LoadResult:
    rules: Rules
    source: str            # "sheets" | "cache" | "fallback"
    error: str = ""        # причина, если данные не из таблицы


_last_good: Rules | None = None


def load_rules(fetch: Callable[[], dict] | None, fallback_path: Path) -> LoadResult:
    """Таблица -> последние корректные данные -> data/fallback.json."""
    global _last_good
    error = "Google Sheets не подключён"
    if fetch is not None:
        try:
            rules = parse_rules(fetch())
        except Exception as exc:  # noqa: BLE001 — сеть, доступ, формат: любая причина = запасной вариант
            error = f"{type(exc).__name__}: {exc}"
            log.warning("Не удалось получить правила из Google Sheets: %s", error)
        else:
            _last_good = rules
            return LoadResult(rules, "sheets")
    if _last_good is not None:
        return LoadResult(_last_good, "cache", error)
    raw = json.loads(fallback_path.read_text(encoding="utf-8"))
    return LoadResult(parse_rules(raw), "fallback", error)
