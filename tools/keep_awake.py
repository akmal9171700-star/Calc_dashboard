"""Открывает калькулятор в настоящем браузере, чтобы Streamlit Cloud не усыплял приложение.

Если приложение уже уснуло, нажимает кнопку «Yes, get this app back up!» и ждёт запуска.
Адрес берётся из переменной окружения APP_URL. Код возврата 1 означает, что приложение не открылось.
Скрипт запускается только в GitHub Actions и в приложение не входит.
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

URL = os.environ.get("APP_URL", "").strip()
WAKE_BUTTON = "button:has-text('get this app back up')"
APP_READY = 'input[type="number"]'     # поля количества есть только у загруженного калькулятора
TIMEOUT = 300                          # секунд: пробуждение занимает 1–3 минуты
RETRY_CLICK_AFTER = 90                 # секунд до повторного нажатия, если кнопка не пропала


def first_match(page, selector):
    """Ищет элемент на странице и во всех её фреймах (приложение может открываться во фрейме)."""
    for frame in page.frames:
        locator = frame.locator(selector)
        if locator.count():
            return locator.first
    return None


def main() -> int:
    if not URL.startswith("http"):
        print("Не задан адрес приложения (переменная APP_URL).")
        return 1
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=90_000)
        last_click = 0.0
        deadline = time.time() + TIMEOUT
        while time.time() < deadline:
            if first_match(page, APP_READY):
                print("Приложение открыто и работает." + (" Его пришлось разбудить." if last_click else ""))
                page.wait_for_timeout(5000)          # даём сессии зарегистрироваться
                browser.close()
                return 0
            button = first_match(page, WAKE_BUTTON)
            if button and time.time() - last_click > RETRY_CLICK_AFTER:
                print("Приложение спало, нажимаю кнопку пробуждения.")
                button.click()
                last_click = time.time()
            page.wait_for_timeout(2000)
        print("Приложение не открылось за отведённое время.")
        browser.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())
