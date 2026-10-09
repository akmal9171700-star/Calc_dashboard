"""Расчёт вознаграждения агента.

Только бизнес-логика: никакого Streamlit и Google Sheets.
Все деньги считаются на Decimal, округление выполняется только для итогов.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext

WILDCARD = "*"          # «любое значение» в таблице ставок
PLAN_YES = "yes"        # месячный план выполнен
PLAN_NO = "no"          # месячный план не выполнен
ZERO = Decimal(0)
_PRECISION = 60


class RulesError(ValueError):
    """Для комбинации нет подходящего правила или их несколько."""


@dataclass(frozen=True)
class Option:
    """Вариант выбора (категория или регион) с названиями на двух языках."""

    code: str
    ru: str
    uz: str

    def label(self, lang: str) -> str:
        return (self.uz if lang == "uz" else self.ru) or self.ru


@dataclass(frozen=True)
class Tariff:
    name: str
    kind: str              # тип в нижнем регистре: "bundle", "обычный"
    price_vat: Decimal     # цена с НДС
    main_tariff: str       # у Bonus-тарифа — название основного, иначе ""
    fixed_reward: Decimal  # фикс за 1-й месяц (только Bonus)
    third_month: bool      # платится ли 3-й месяц
    order: int

    @property
    def is_bonus(self) -> bool:
        return bool(self.main_tariff)


@dataclass(frozen=True)
class RateRow:
    kind: str
    category: str                                   # код или "*"
    plan: str                                       # "yes" | "no" | "*"
    region: str                                     # код или "*"
    months: tuple[Decimal, Decimal, Decimal]        # доли: 0.65 = 65 %


@dataclass(frozen=True)
class Rules:
    vat_percent: Decimal
    tariffs: tuple[Tariff, ...]                     # только активные, по порядку
    rates: tuple[RateRow, ...]
    categories: tuple[Option, ...]
    regions: tuple[Option, ...]

    def tariff(self, name: str) -> Tariff:
        for tariff in self.tariffs:
            if tariff.name.casefold() == name.casefold():
                return tariff
        raise RulesError(f"Тариф «{name}» не найден среди активных")


@dataclass(frozen=True)
class Line:
    """Расчёт по одному тарифу."""

    tariff: str
    quantity: int
    rates: tuple[Decimal, Decimal, Decimal]         # действующие ставки
    fixed: Decimal | None                           # фикс за 1-й месяц у Bonus
    months: tuple[Decimal, Decimal, Decimal]        # точные суммы по месяцам


@dataclass(frozen=True)
class Result:
    lines: tuple[Line, ...]
    month_totals: tuple[int, int, int]              # округлены до целого сума
    total: int                                      # сумма округлённых месяцев


def money(value: Decimal) -> int:
    """Округление до целого сума (0,5 — вверх)."""
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def find_rate(rules: Rules, kind: str, category: str,
              plan_met: bool, region: str) -> RateRow:
    """Самое конкретное правило; при пустом или неоднозначном выборе — ошибка."""
    plan = PLAN_YES if plan_met else PLAN_NO
    best: RateRow | None = None
    best_score = -1
    tie = False
    for row in rules.rates:
        if row.kind != kind:
            continue
        if row.category not in (WILDCARD, category):
            continue
        if row.plan not in (WILDCARD, plan):
            continue
        if row.region not in (WILDCARD, region):
            continue
        score = sum(v != WILDCARD for v in (row.category, row.plan, row.region))
        if score > best_score:
            best, best_score, tie = row, score, False
        elif score == best_score:
            tie = True
    where = f"тип «{kind}», категория «{category}», план «{plan}», регион «{region}»"
    if best is None:
        raise RulesError(f"Нет ставки для: {where}")
    if tie:
        raise RulesError(f"Несколько одинаково подходящих ставок для: {where}")
    return best


def calculate(rules: Rules, category: str, region: str, plan_met: bool,
              quantities: dict[str, int]) -> Result:
    """Вознаграждение за 1-й, 2-й и 3-й месяцы по подключениям текущего месяца."""
    if category not in {o.code for o in rules.categories}:
        raise ValueError(f"Неизвестная категория: {category!r}")
    if region not in {o.code for o in rules.regions}:
        raise ValueError(f"Неизвестный регион: {region!r}")
    names = {t.name for t in rules.tariffs}
    for name, qty in quantities.items():
        if name not in names:
            raise ValueError(f"Неизвестный тариф: {name!r}")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
            raise ValueError(f"Количество для «{name}» должно быть целым числом от 0")

    lines: list[Line] = []
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        vat_divisor = 1 + rules.vat_percent / 100
        for tariff in rules.tariffs:
            qty = quantities.get(tariff.name, 0)
            if qty == 0:
                continue
            main = rules.tariff(tariff.main_tariff) if tariff.is_bonus else tariff
            r1, r2, r3 = find_rate(rules, main.kind, category, plan_met, region).months
            if not main.third_month:
                r3 = ZERO
            base = main.price_vat / vat_divisor            # цена без НДС
            first = tariff.fixed_reward * qty if tariff.is_bonus else r1 * base * qty
            lines.append(Line(
                tariff=tariff.name,
                quantity=qty,
                rates=(r1, r2, r3),
                fixed=tariff.fixed_reward if tariff.is_bonus else None,
                months=(first, r2 * base * qty, r3 * base * qty),
            ))
        totals = tuple(money(sum((ln.months[i] for ln in lines), ZERO)) for i in range(3))
    return Result(lines=tuple(lines), month_totals=totals, total=sum(totals))  # type: ignore[arg-type]
