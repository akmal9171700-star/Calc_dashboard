"""Проверка интерфейса без браузера (Streamlit AppTest)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parent.parent / "app.py")


def clean(text):
    return text.replace("\u00a0", " ")


@pytest.fixture
def app():
    return AppTest.from_file(APP, default_timeout=30).run()


def test_opens_without_errors_and_asks_for_input(app):
    assert not app.exception
    assert clean(app.metric[0].value) == "0 сум"
    assert app.info                                  # подсказка «введите количество»
    assert app.warning                               # запасные данные (таблица не подключена)


def test_excel_example_in_interface(app):
    app.number_input(key="qty:Salom Pro").set_value(500)
    app.number_input(key="qty:Bonus Salom Pro").set_value(500).run()
    assert not app.exception
    values = [clean(m.value) for m in app.metric]
    assert values == ["111 357 143 сум", "29 214 286", "46 428 571", "35 714 286"]


def test_plan_not_met_and_region_change_result(app):
    app.number_input(key="qty:Balance").set_value(10)
    app.radio[3].set_value(False).run()             # план не выполнен
    app.radio[2].set_value("M").run()               # М-РЕГИОН
    assert clean(app.metric[0].value) == "638 392 сум"      # 2 × 319 196


def test_uzbek_language_switch(app):
    app.radio[0].set_value("O'zbekcha").run()
    assert app.title[0].value == "Mukofot kalkulyatori"
    assert "so'm" in app.metric[0].value


def test_design_files_are_shipped():
    root = Path(APP).parent
    assert (root / "assets" / "uztelecom-logo.png").stat().st_size > 1000
    assert "#3D6394" in (root / "assets" / "style.css").read_text(encoding="utf-8")


def test_app_works_without_style_file(monkeypatch):
    real = Path.read_text

    def fake(self, *args, **kwargs):
        if self.name == "style.css":
            raise FileNotFoundError(self)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake)
    page = AppTest.from_file(APP, default_timeout=30).run()
    assert not page.exception and page.metric
