"""Интерфейс калькулятора (Streamlit). Бизнес-логика — в calc.py, данные — в sheets.py."""
from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

import streamlit as st

import calc
import sheets
from texts import LANGUAGES, kind_label, t

CACHE_TTL_SECONDS = 300
FALLBACK_PATH = Path(__file__).parent / "data" / "fallback.json"
ASSETS = Path(__file__).parent / "assets"

st.set_page_config(page_title="Калькулятор вознаграждения", page_icon="🧮", layout="centered")
log = logging.getLogger("app")


def _sheets_fetcher():
    """Функция чтения таблицы, если в Secrets есть ключ и ID; иначе None."""
    try:
        credentials = dict(st.secrets["gcp_service_account"])
        spreadsheet_id = st.secrets["sheets"]["spreadsheet_id"]
    except Exception:  # noqa: BLE001 — секреты не заданы (локальный запуск)
        return None
    return lambda: sheets.fetch_raw(credentials, spreadsheet_id)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_rules() -> sheets.LoadResult:
    return sheets.load_rules(_sheets_fetcher(), FALLBACK_PATH)


def fmt(amount: int) -> str:
    return f"{amount:,}".replace(",", "\u00a0")


def pct(rate: Decimal) -> str:
    return f"{(rate * 100).normalize():f}\u00a0%" if rate else "—"


def rates_text(line: calc.Line, lang: str) -> str:
    first = f"{t(lang, 'fixed')} {fmt(int(line.fixed))}" if line.fixed is not None else pct(line.rates[0])
    return " / ".join([first, pct(line.rates[1]), pct(line.rates[2])])


def load_styles() -> None:
    """Подключает assets/style.css; без файла калькулятор работает в обычном виде."""
    try:
        css = (ASSETS / "style.css").read_text(encoding="utf-8")
    except OSError:
        return
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


# ---------------------------------------------------------------- страница
load_styles()
header_logo, header_lang = st.columns(2)
if (ASSETS / "uztelecom-logo.png").exists():
    header_logo.image(str(ASSETS / "uztelecom-logo.png"), width=160)
with header_lang:
    lang_name = st.radio("Til / Язык", list(LANGUAGES.values()), horizontal=True,
                         label_visibility="collapsed")
lang = next(code for code, name in LANGUAGES.items() if name == lang_name)

try:
    loaded = get_rules()
except Exception:  # noqa: BLE001 — нет ни таблицы, ни резервной копии
    log.exception("Правила недоступны")
    st.error(t(lang, "fatal"))
    st.stop()
rules = loaded.rules

st.title(t(lang, "title"))
if loaded.source != "sheets":
    st.warning(t(lang, "stale"))

summary = st.container()          # итог показываем вверху, заполняем после ввода

category = st.radio(t(lang, "category"), [o.code for o in rules.categories],
                    format_func=lambda c: next(o for o in rules.categories if o.code == c).label(lang),
                    horizontal=True)
region = st.radio(t(lang, "region"), [o.code for o in rules.regions],
                  format_func=lambda c: next(o for o in rules.regions if o.code == c).label(lang),
                  horizontal=True)
plan_met = st.radio(t(lang, "plan"), [True, False],
                    format_func=lambda v: t(lang, "plan_yes" if v else "plan_no"),
                    horizontal=True)

st.subheader(t(lang, "connections"))
quantities: dict[str, int] = {}
shown_kinds: list[str] = []
for tariff in rules.tariffs:
    kind = rules.tariff(tariff.main_tariff).kind if tariff.is_bonus else tariff.kind
    if kind not in shown_kinds:
        shown_kinds.append(kind)
for kind in shown_kinds:
    st.markdown(f"**{kind_label(lang, kind)}**")
    for tariff in rules.tariffs:
        owner = rules.tariff(tariff.main_tariff).kind if tariff.is_bonus else tariff.kind
        if owner != kind:
            continue
        label = tariff.name if tariff.is_bonus else f"{tariff.name} · {fmt(int(tariff.price_vat))}"
        quantities[tariff.name] = st.number_input(
            label, min_value=0, step=1, value=0, format="%d", key=f"qty:{tariff.name}")

try:
    result = calc.calculate(rules, category, region, plan_met, quantities)
except (ValueError, calc.RulesError):
    log.exception("Ошибка расчёта")
    st.error(t(lang, "fatal"))
    st.stop()

currency = t(lang, "currency")
with summary:
    st.metric(t(lang, "total"), f"{fmt(result.total)} {currency}")
    if result.lines:
        for column, i in zip(st.columns(3), range(3)):
            column.metric(t(lang, "month", n=i + 1), fmt(result.month_totals[i]))
    else:
        st.info(t(lang, "empty"))

if result.lines:
    st.subheader(t(lang, "breakdown"))
    for i, line in enumerate(result.lines):
        with st.container(key=f"line_{i}"):
            st.markdown(f"**{line.tariff}** × {line.quantity}")
            st.caption(rates_text(line, lang))
            rows = "\n".join(
                f"| {t(lang, 'month', n=i + 1)} | {fmt(calc.money(line.months[i]))} |" for i in range(3))
            st.markdown(f"| {t(lang, 'period')} | {t(lang, 'amount')} |\n|:--|--:|\n{rows}")
    st.caption(t(lang, "vat_note", vat=f"{rules.vat_percent.normalize():f}"))
    st.caption(t(lang, "rounding_note"))
