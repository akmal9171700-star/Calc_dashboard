"""Тексты интерфейса на русском и узбекском (латиница)."""
from __future__ import annotations

LANGUAGES = {"ru": "Русский", "uz": "O'zbekcha"}

TEXTS: dict[str, dict[str, str]] = {
    "ru": {
        "title": "Калькулятор вознаграждения",
        "total": "Итого за 3 месяца",
        "month": "{n}-й месяц",
        "currency": "сум",
        "empty": "Введите количество подключений — расчёт появится здесь.",
        "category": "Категория",
        "region": "Регион",
        "plan": "Месячный план",
        "plan_yes": "Выполнен",
        "plan_no": "Не выполнен",
        "connections": "Подключения текущего месяца",
        "breakdown": "Разбивка по тарифам",
        "period": "Месяц",
        "amount": "Сумма, сум",
        "fixed": "фикс.",
        "vat_note": "Расчёт ведётся от цены без НДС (НДС {vat} %).",
        "rounding_note": "Суммы округлены до целого сума, поэтому итог может отличаться от суммы строк таблицы на 1 сум.",
        "stale": "Не удалось обновить правила, показан расчёт по последним сохранённым. Они могут быть устаревшими.",
        "fatal": "Калькулятор временно недоступен. Попробуйте позже.",
        "kind:bundle": "Тарифы BUNDLE",
        "kind:обычный": "Обычные тарифы",
    },
    "uz": {
        "title": "Mukofot kalkulyatori",
        "total": "3 oy uchun jami",
        "month": "{n}-oy",
        "currency": "so'm",
        "empty": "Ulanishlar sonini kiriting — hisob-kitob shu yerda chiqadi.",
        "category": "Kategoriya",
        "region": "Hudud",
        "plan": "Oylik reja",
        "plan_yes": "Bajarilgan",
        "plan_no": "Bajarilmagan",
        "connections": "Joriy oy ulanishlari",
        "breakdown": "Tariflar bo'yicha tafsilot",
        "period": "Oy",
        "amount": "Summa, so'm",
        "fixed": "qat'iy",
        "vat_note": "Hisob-kitob QQSsiz narxdan amalga oshiriladi (QQS {vat} %).",
        "rounding_note": "Summalar butun so'mgacha yaxlitlangan, shuning uchun jami summa jadval qatorlari yig'indisidan 1 so'mga farq qilishi mumkin.",
        "stale": "Qoidalarni yangilab bo'lmadi, oxirgi saqlangan qoidalar bo'yicha hisob ko'rsatilmoqda. Ular eskirgan bo'lishi mumkin.",
        "fatal": "Kalkulyator vaqtincha ishlamayapti. Keyinroq urinib ko'ring.",
        "kind:bundle": "BUNDLE tariflar",
        "kind:обычный": "Oddiy tariflar",
    },
}


def t(lang: str, key: str, **values: object) -> str:
    text = TEXTS[lang][key]
    return text.format(**values) if values else text


def kind_label(lang: str, kind: str) -> str:
    return TEXTS[lang].get(f"kind:{kind}", kind[:1].upper() + kind[1:])
