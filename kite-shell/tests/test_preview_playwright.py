"""Playwright headless Chromium E2E tests for kite-shell/preview/."""

from __future__ import annotations

from typing import Iterator

import pytest
from playwright.sync_api import Page, sync_playwright


@pytest.fixture()
def clean_page(preview_server_url: str) -> Iterator[Page]:
    console_errors: list[str] = []
    page_errors: list[str] = []
    bad_responses: list[str] = []
    failed_requests: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1366, "height": 768})
        page = context.new_page()

        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda err: page_errors.append(str(err)))
        page.on(
            "response",
            lambda resp: bad_responses.append(f"{resp.status} {resp.url}") if resp.status >= 400 else None,
        )
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.url}: {req.failure}"))

        page.goto(preview_server_url, wait_until="networkidle")
        yield page

        context.close()
        browser.close()

    assert not console_errors, f"Console errors detected: {console_errors}"
    assert not page_errors, f"Uncaught page errors detected: {page_errors}"
    assert not bad_responses, f"HTTP >= 400 responses detected: {bad_responses}"
    assert not failed_requests, f"Failed network requests detected: {failed_requests}"


def test_preview_boots_cleanly_at_folio_resolutions(clean_page: Page) -> None:
    for width, height in ((1366, 768), (1600, 900)):
        clean_page.set_viewport_size({"width": width, "height": height})
        assert clean_page.locator('[data-testid="taskbar"]').is_visible()
        assert clean_page.locator('[data-testid="kite-settings-window"]').is_visible()
        assert "8G" in clean_page.locator('[data-testid="hw-telemetry"]').inner_text()


def test_taskbar_alignment_toggle(clean_page: Page) -> None:
    taskbar = clean_page.locator('[data-testid="taskbar"]')
    dock = clean_page.locator('[data-testid="taskbar-dock"]')

    assert taskbar.get_attribute("data-alignment") == "center"
    center_x = dock.bounding_box()["x"]

    clean_page.locator('[data-testid="taskbar-align-toggle"]').click()
    assert taskbar.get_attribute("data-alignment") == "left"
    left_x = dock.bounding_box()["x"]
    assert left_x < center_x - 50

    clean_page.locator('[data-testid="setting-align-center"]').click()
    assert taskbar.get_attribute("data-alignment") == "center"


def test_start_menu_search_and_platform_tags(clean_page: Page) -> None:
    clean_page.locator('[data-testid="start-button"]').click()
    start_menu = clean_page.locator('[data-testid="start-menu"]')
    assert start_menu.is_visible()

    text = start_menu.inner_text()
    for badge in ("[Win]", "[Android]", "[macOS]"):
        assert badge in text

    search = clean_page.locator('[data-testid="start-search-input"]')
    search.fill(".apk")
    assert clean_page.locator('#start-apps-grid [data-platform="android"]').count() >= 1
    assert clean_page.locator('#start-apps-grid [data-platform="win"]').count() == 0

    search.fill("")
    clean_page.locator('[data-testid="filter-win"]').click()
    assert clean_page.locator('#start-apps-grid [data-platform="win"]').count() >= 2
    assert clean_page.locator('#start-apps-grid [data-platform="android"]').count() == 0

    clean_page.locator('[data-testid="filter-macos"]').click()
    assert clean_page.locator('#start-apps-grid [data-platform="macos"]').count() >= 2

    clean_page.locator('[data-testid="start-all-apps-toggle"]').click()
    assert "is-list" in (clean_page.locator("#start-apps-grid").get_attribute("class") or "")

    clean_page.locator('[data-testid="start-power-btn"]').click()
    assert clean_page.locator('[data-testid="power-menu"]').is_visible()


def test_quick_settings_win_a(clean_page: Page) -> None:
    clean_page.keyboard.press("Alt+a")
    qs = clean_page.locator('[data-testid="quick-settings"]')
    assert qs.is_visible()

    clean_page.locator('[data-testid="qs-glass-fx-toggle"]').click()
    assert clean_page.locator("#desktop-root").get_attribute("data-blur-mode") == "static"

    clean_page.locator('[data-testid="qs-glass-fx-toggle"]').click()
    assert clean_page.locator("#desktop-root").get_attribute("data-blur-mode") == "kawase_2pass"

    clean_page.locator('[data-pm="Turbo"]').click()
    assert "is-active" in (clean_page.locator('[data-pm="Turbo"]').get_attribute("class") or "")
    clean_page.locator('[data-testid="mixer-waydroid"]').fill("45")


def test_notifications_and_calendar_win_n(clean_page: Page) -> None:
    clean_page.locator('[data-testid="hotkey-win-n"]').click()
    nc = clean_page.locator('[data-testid="notification-center"]')
    assert nc.is_visible()
    assert "[Android]" in clean_page.locator('[data-testid="notification-list"]').inner_text()

    before_month = clean_page.locator("#cal-month-label").inner_text()
    clean_page.locator('[data-testid="cal-next"]').click()
    assert clean_page.locator("#cal-month-label").inner_text() != before_month

    clean_page.locator('[data-testid="notifications-clear-btn"]').click()
    assert "No new notifications" in clean_page.locator('[data-testid="notification-list"]').inner_text()


def test_snap_layouts_win_z(clean_page: Page) -> None:
    win = clean_page.locator('[data-testid="kite-settings-window"]')
    canvas_box = clean_page.locator('[data-testid="desktop-canvas"]').bounding_box()

    clean_page.locator('[data-testid="hotkey-win-z"]').click()
    assert clean_page.locator('[data-testid="snap-layouts"]').is_visible()
    clean_page.locator('[data-snap="left-half"]').click()
    clean_page.wait_for_timeout(300)
    left_box = win.bounding_box()
    assert abs(left_box["width"] - (canvas_box["width"] - 24) / 2) <= 4
    assert left_box["x"] < 20

    clean_page.locator('[data-testid="hotkey-win-z"]').click()
    clean_page.locator('[data-snap="right-half"]').click()
    clean_page.wait_for_timeout(300)
    right_box = win.bounding_box()
    assert right_box["x"] > canvas_box["width"] / 2 - 10

    clean_page.locator('[data-testid="hotkey-win-z"]').click()
    clean_page.locator('[data-snap="split-60"]').click()
    clean_page.wait_for_timeout(300)
    split_box = win.bounding_box()
    assert split_box["width"] > left_box["width"] + 80

    clean_page.locator('[data-testid="hotkey-win-z"]').click()
    clean_page.locator('[data-snap="top-left"]').click()
    clean_page.wait_for_timeout(300)
    tl_box = win.bounding_box()
    assert tl_box["height"] < left_box["height"] / 2 + 20


def test_kite_settings_presets_and_live_css(clean_page: Page) -> None:
    for testid, accent in (
        ("preset-frosted-obsidian", "#818CF8"),
        ("preset-emerald-glass", "#10B981"),
        ("preset-sunset-mica", "#FB923C"),
        ("preset-ultra-light-flat", "#60A5FA"),
        ("preset-aero-blue", "#38BDF8"),
    ):
        clean_page.locator(f'[data-testid="{testid}"]').click()
        prop = clean_page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent-color').trim()")
        assert prop.upper() == accent

    clean_page.locator('[data-testid="slider-transparency"]').fill("0.55")
    clean_page.locator('[data-testid="slider-transparency"]').dispatch_event("input")
    assert clean_page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--glass-alpha').trim()") == "0.55"

    clean_page.locator('[data-testid="slider-radius"]').fill("18")
    clean_page.locator('[data-testid="slider-radius"]').dispatch_event("input")
    assert clean_page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--corner-radius').trim()") == "18px"

    clean_page.locator('.cat-btn[data-cat="performance"]').click()
    clean_page.locator('[data-testid="toggle-mitigations-off"]').check()
    assert clean_page.locator('[data-testid="mitigations-warning"]').is_visible()


def test_hardware_simulator_4g_8g_16g_ac_battery(clean_page: Page) -> None:
    runtime_pre = clean_page.locator('[data-testid="runtime-conf-preview"]')
    root = clean_page.locator("#desktop-root")

    # 8G AC default
    assert root.get_attribute("data-blur-mode") == "kawase_2pass"
    assert "passes = 2" in runtime_pre.inner_text()
    blur_ac = clean_page.evaluate("getComputedStyle(document.getElementById('taskbar')).backdropFilter")
    assert "blur(" in blur_ac

    # 8G Battery -> 1 pass, size <= 4
    clean_page.locator('[data-testid="hw-power-battery"]').click()
    assert root.get_attribute("data-blur-mode") == "kawase_1pass"
    assert "passes = 1" in runtime_pre.inner_text()
    assert "size = 4" in runtime_pre.inner_text()

    # 4G -> Static Acrylic, backdropFilter none, enabled = false
    clean_page.locator('[data-testid="hw-ram-4G"]').click()
    assert root.get_attribute("data-blur-mode") == "static"
    assert "enabled = false" in runtime_pre.inner_text()
    blur_4g = clean_page.evaluate("getComputedStyle(document.getElementById('taskbar')).backdropFilter")
    assert blur_4g == "none"

    # 16G AC -> kawase_full, passes = 2
    clean_page.locator('[data-testid="hw-ram-16G"]').click()
    clean_page.locator('[data-testid="hw-power-ac"]').click()
    assert root.get_attribute("data-blur-mode") == "kawase_full"
    assert "passes = 2" in runtime_pre.inner_text()


def test_window_maximize_restore_drag_containment_and_taskbar_sync(clean_page: Page) -> None:
    win = clean_page.locator('[data-testid="kite-settings-window"]')
    canvas_box = clean_page.locator('[data-testid="desktop-canvas"]').bounding_box()
    orig_box = win.bounding_box()

    # True Maximize & Restore toggle
    win.locator('[data-action="max"]').click()
    clean_page.wait_for_timeout(300)
    assert win.get_attribute("data-maximized") == "true"
    assert win.get_attribute("data-snap-zone") == "none"
    max_box = win.bounding_box()
    assert abs(max_box["width"] - (canvas_box["width"] - 16)) <= 4
    assert abs(max_box["height"] - (canvas_box["height"] - 16)) <= 4

    win.locator('[data-action="max"]').click()
    clean_page.wait_for_timeout(300)
    assert win.get_attribute("data-maximized") == "false"
    restored_box = win.bounding_box()
    assert abs(restored_box["width"] - orig_box["width"]) <= 4
    assert abs(restored_box["height"] - orig_box["height"]) <= 4

    # Drag containment inside #desktop-canvas
    bar_box = win.locator(".window-titlebar").bounding_box()
    start_x = bar_box["x"] + 80
    start_y = bar_box["y"] + bar_box["height"] / 2
    clean_page.mouse.move(start_x, start_y)
    clean_page.mouse.down()
    clean_page.mouse.move(2200, 1200, steps=5)
    clean_page.mouse.up()
    clean_page.wait_for_timeout(150)
    dragged_box = win.bounding_box()
    assert dragged_box["x"] <= canvas_box["x"] + canvas_box["width"] - 160 + 2
    assert dragged_box["y"] <= canvas_box["y"] + canvas_box["height"] - 40 + 2

    # Close kite-settings -> taskbar .is-open and .is-active removed
    win.locator('[data-action="close"]').click()
    assert not win.is_visible()
    ks_tb_classes = clean_page.locator('.tb-app[data-focus-window="kite-settings"]').get_attribute("class") or ""
    assert "is-open" not in ks_tb_classes
    assert "is-active" not in ks_tb_classes

    # Launch terminal -> taskbar .is-open and .is-active added
    clean_page.locator('.desktop-icon[data-launch="terminal"]').click()
    term_win = clean_page.locator('[data-testid="window-terminal"]')
    assert term_win.is_visible()
    term_tb = clean_page.locator('.tb-app[data-focus-window="terminal"]')
    term_tb_classes = term_tb.get_attribute("class") or ""
    assert "is-open" in term_tb_classes
    assert "is-active" in term_tb_classes

    # Minimize terminal -> hidden, keeps .is-open, loses .is-active; click taskbar restores it
    term_win.locator('[data-action="min"]').click()
    assert not term_win.is_visible()
    term_tb_min_classes = term_tb.get_attribute("class") or ""
    assert "is-open" in term_tb_min_classes
    assert "is-active" not in term_tb_min_classes
    term_tb.click()
    assert term_win.is_visible()
    assert "is-active" in (term_tb.get_attribute("class") or "")


def test_meta_s_and_narrow_left_half_no_overflow(clean_page: Page) -> None:
    # Meta+s opens Start Menu
    clean_page.evaluate(
        "window.dispatchEvent(new KeyboardEvent('keydown', { key: 's', metaKey: true, bubbles: true, cancelable: true }))"
    )
    start_menu = clean_page.locator('[data-testid="start-menu"]')
    assert start_menu.is_visible()
    clean_page.keyboard.press("Escape")
    assert not start_menu.is_visible()

    # Snapped left-half at 1024x768 has zero horizontal overflow in .studio-content
    clean_page.set_viewport_size({"width": 1024, "height": 768})
    clean_page.locator('[data-testid="hotkey-win-z"]').click()
    clean_page.locator('[data-snap="left-half"]').click()
    clean_page.wait_for_timeout(300)
    overflow = clean_page.evaluate(
        """() => {
            const el = document.querySelector('#win-kite-settings .studio-content');
            return { scrollWidth: el.scrollWidth, clientWidth: el.clientWidth };
        }"""
    )
    assert overflow["scrollWidth"] <= overflow["clientWidth"], f"Horizontal overflow detected: {overflow}"


def test_taskbar_v2_icons_morphing_pills_and_specular_borders(clean_page: Page) -> None:
    svgs = clean_page.locator(".tb-app svg")
    assert svgs.count() >= 4
    active_pill_w = clean_page.evaluate(
        "parseFloat(getComputedStyle(document.querySelector('.tb-app.is-active .tb-pill-dot')).width)"
    )
    open_pill_w = clean_page.evaluate(
        "parseFloat(getComputedStyle(document.querySelector('.tb-app.is-open:not(.is-active) .tb-pill-dot')).width)"
    )
    assert active_pill_w >= 14.0
    assert 4.0 <= open_pill_w <= 8.0
    border_top = clean_page.evaluate("getComputedStyle(document.getElementById('win-kite-settings')).borderTopColor")
    assert "rgba" in border_top or "rgb" in border_top


def test_ai_spotlight_search_and_clickable_uri_cards(clean_page: Page) -> None:
    pill = clean_page.locator('[data-testid="taskbar-search-pill"]')
    assert "Win+S" in pill.inner_text()
    pill.click()
    spotlight = clean_page.locator('[data-testid="ai-spotlight"]')
    assert spotlight.is_visible()
    clean_page.locator('[data-testid="spotlight-input"]').fill("greenhouse")
    cards = clean_page.locator('[data-testid="spotlight-results"] .spotlight-card')
    assert cards.count() >= 2
    href = cards.first.get_attribute("href") or ""
    assert href.startswith("kite://open?path=")
    assert "Tier 0" in clean_page.locator('[data-testid="spotlight-tier-badge"]').inner_text()


def test_bento_grid_and_ai_indexing_studio_tab(clean_page: Page) -> None:
    clean_page.locator('.cat-btn[data-cat="performance"]').click()
    bento = clean_page.locator('[data-testid="bento-grid"]')
    assert bento.is_visible()
    assert clean_page.locator('[data-testid="bento-grid"] .bento-card').count() == 4
    assert "crocus" in clean_page.locator('[data-testid="bento-gpu"]').inner_text()
    assert "DXVK 1.10.3" in clean_page.locator('[data-testid="bento-bridge"]').inner_text()

    clean_page.locator('[data-testid="cat-ai-indexing"]').click()
    assert clean_page.locator('[data-testid="pane-ai-indexing"]').is_visible()
    clean_page.locator('[data-testid="ai-provider-select"]').select_option("gemini")
    clean_page.locator('[data-testid="ai-token-slider"]').fill("350")
    clean_page.locator('[data-testid="ai-token-slider"]').dispatch_event("input")
    assert "350 tok" in clean_page.locator("#val-ai-budget").inner_text()

    clean_page.locator('[data-testid="taskbar-search-pill"]').click()
    clean_page.locator('[data-testid="spotlight-input"]').fill("capstone")
    assert "BYOK gemini" in clean_page.locator('[data-testid="spotlight-tier-badge"]').inner_text()
    assert not clean_page.locator('[data-testid="ai-session-cost"]').inner_text().startswith("0 tokens")
