"""Расчёт: примеры из CALC.xlsx, все категории и регионы, нулевые и неверные значения."""
from decimal import Decimal
from fractions import Fraction

import pytest

import calc
from helpers import raw_data, rules_from, row_of


@pytest.fixture(scope="module")
def rules():
    return rules_from()


def run(rules, quantities, category="TOP", region="MBR", plan_met=True):
    return calc.calculate(rules, category, region, plan_met, quantities)


# ---- пример из листа «пример расчёта дилера из ТОП» --------------------------
def test_excel_example_top_500_salom_pro_plus_500_bonus(rules):
    res = run(rules, {"Salom Pro": 500, "Bonus Salom Pro": 500})
    main, bonus = res.lines
    # точные значения как в Excel (D4:F4, D5:F5)
    assert main.months[0] == main.months[1]
    assert round(main.months[0], 2) == Decimal("23214285.71")
    assert round(main.months[2], 2) == Decimal("17857142.86")
    assert bonus.months[0] == 6_000_000                       # фикс 12 000 × 500
    assert round(bonus.months[1], 2) == Decimal("23214285.71")
    assert round(bonus.months[2], 2) == Decimal("17857142.86")
    # итоги Excel: D6=29 214 285,71; E6=46 428 571,43; F6=35 714 285,71; G6=111 357 142,86
    assert res.month_totals == (29_214_286, 46_428_571, 35_714_286)
    assert res.total == 111_357_143


def test_per_sim_top_sheet_salom_pro(rules):
    """Лист «ТОП»: 1,8 × цена без НДС на одну SIM = 128 571,43."""
    res = run(rules, {"Salom Pro": 1})
    assert res.month_totals == (46_429, 46_429, 35_714)
    assert res.total == 128_572            # сумма округлённых месяцев


# ---- категории, регионы, план ----------------------------------------------
@pytest.mark.parametrize("category,expected", [
    ("TOP", (46_429, 46_429, 35_714)),     # 65 / 65 / 50
    ("L1", (42_857, 46_429, 0)),           # 60 / 65 / —
    ("L2", (42_857, 42_857, 0)),           # 60 / 60 / —
])
def test_plan_met_rates_by_category(rules, category, expected):
    assert run(rules, {"Salom Pro": 1}, category=category).month_totals == expected


@pytest.mark.parametrize("category", ["TOP", "L1", "L2"])
@pytest.mark.parametrize("region,expected", [
    ("MBR", (32_143, 32_143, 0)),          # 45 / 45
    ("M", (39_286, 39_286, 0)),            # 55 / 55
])
def test_plan_not_met_uses_region_rates_for_all_categories(rules, category, region, expected):
    res = run(rules, {"Salom Pro": 1}, category=category, region=region, plan_met=False)
    assert res.month_totals == expected


def test_third_month_only_for_salom_pro(rules):
    ideal = run(rules, {"Ideal Plus": 10})
    assert ideal.month_totals[2] == 0 and ideal.month_totals[0] == 493_304
    lux = run(rules, {"Mobile Lux": 10})
    assert lux.month_totals[2] == 0
    assert run(rules, {"Salom Pro": 10}).month_totals[2] > 0


def test_ordinary_tariffs_depend_only_on_region(rules):
    expected = {"MBR": (261_161, 261_161, 0), "M": (319_196, 319_196, 0)}   # 65 000 без НДС × 45 % / 55 % × 10
    for category in ("TOP", "L1", "L2"):
        for plan_met in (True, False):
            for region, months in expected.items():
                res = run(rules, {"Balance": 10}, category, region, plan_met)
                assert res.month_totals == months


def test_bonus_uses_main_tariff_price_and_third_month_flag(rules):
    res = run(rules, {"Bonus Salom Pro": 100})
    assert res.month_totals == (1_200_000, 4_642_857, 3_571_429)
    ideal = run(rules, {"Bonus Ideal Plus": 100})
    assert ideal.month_totals == (1_300_000, 4_933_036, 0)       # у Ideal Plus 3-го месяца нет


def test_bonus_fixed_reward_ignores_plan_status(rules):
    for plan_met in (True, False):
        assert run(rules, {"Bonus Salom Pro": 10}, plan_met=plan_met).month_totals[0] == 120_000


# ---- нули и неверные данные -------------------------------------------------
def test_zero_and_empty_input(rules):
    for quantities in ({}, {"Salom Pro": 0, "Balance": 0}):
        res = run(rules, quantities)
        assert res.lines == () and res.month_totals == (0, 0, 0) and res.total == 0


@pytest.mark.parametrize("bad", [-1, 1.5, "10", None, True])
def test_bad_quantity_is_rejected(rules, bad):
    with pytest.raises(ValueError):
        run(rules, {"Salom Pro": bad})


def test_unknown_tariff_category_region_rejected(rules):
    with pytest.raises(ValueError):
        run(rules, {"Nope": 1})
    with pytest.raises(ValueError):
        run(rules, {}, category="XX")
    with pytest.raises(ValueError):
        run(rules, {}, region="XX")


# ---- точность и округление ---------------------------------------------------
def test_no_float_noise_when_price_without_vat_is_round():
    raw = raw_data()
    row_of(raw, "Тарифы", "Salom Pro")[2] = 112_000              # без НДС ровно 100 000
    res = run(rules_from(raw), {"Salom Pro": 3})
    assert res.month_totals == (195_000, 195_000, 150_000) and res.total == 540_000


def test_price_change_in_table_changes_result():
    raw = raw_data()
    row_of(raw, "Тарифы", "Balance")[2] = 112_000
    assert run(rules_from(raw), {"Balance": 10}, region="M").month_totals == (550_000, 550_000, 0)


def test_rounding_is_half_up():
    assert calc.money(Decimal("124.5")) == 125
    assert calc.money(Decimal("0.5")) == 1
    assert calc.money(Decimal("124.4999")) == 124


# ---- независимая проверка по всем комбинациям --------------------------------
def _reference(category, region, plan_met, qty):
    """Расчёт на дробях по правилам из ТЗ, без использования таблицы."""
    vat = Fraction(112, 100)
    prices = {"Mini Voice": 45000, "Farzand": 55000, "Optimal": 55000, "Balance": 65000,
              "Salom Pro": 80000, "Ideal Plus": 85000, "Mobile Lux": 101000, "Mobile Elite": 150000}
    bundle = {"Salom Pro", "Ideal Plus", "Mobile Lux", "Mobile Elite"}
    if plan_met:
        bundle_rates = {"TOP": (65, 65, 50), "L1": (60, 65, 0), "L2": (60, 60, 0)}[category]
    else:
        bundle_rates = {"MBR": (45, 45, 0), "M": (55, 55, 0)}[region]
    region_rates = {"MBR": (45, 45, 0), "M": (55, 55, 0)}[region]
    months = [Fraction(0)] * 3
    for name, n in qty.items():
        if name.startswith("Bonus "):
            main, fixed = name[6:], {"Bonus Salom Pro": 12000, "Bonus Ideal Plus": 13000}[name]
            r = bundle_rates
            base = Fraction(prices[main]) / vat
            third = r[2] if main == "Salom Pro" else 0
            parts = [Fraction(fixed) * n, base * r[1] * n / 100, base * third * n / 100]
        else:
            r = bundle_rates if name in bundle else region_rates
            base = Fraction(prices[name]) / vat
            third = r[2] if name == "Salom Pro" else 0
            parts = [base * r[0] * n / 100, base * r[1] * n / 100, base * third * n / 100]
        months = [m + p for m, p in zip(months, parts)]
    half_up = lambda x: int((x * 2 + 1) // 2)
    rounded = [half_up(m) for m in months]
    return rounded, sum(rounded)


@pytest.mark.parametrize("category", ["TOP", "L1", "L2"])
@pytest.mark.parametrize("region", ["MBR", "M"])
@pytest.mark.parametrize("plan_met", [True, False])
def test_matches_independent_reference(rules, category, region, plan_met):
    qty = {"Mini Voice": 3, "Farzand": 7, "Optimal": 11, "Balance": 13, "Salom Pro": 17,
           "Bonus Salom Pro": 19, "Ideal Plus": 23, "Bonus Ideal Plus": 29,
           "Mobile Lux": 31, "Mobile Elite": 37}
    res = calc.calculate(rules, category, region, plan_met, qty)
    months, total = _reference(category, region, plan_met, qty)
    assert list(res.month_totals) == months and res.total == total
