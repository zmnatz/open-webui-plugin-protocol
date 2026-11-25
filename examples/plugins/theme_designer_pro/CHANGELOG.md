# Changelog

## 1.23.0

- From upstream 1.23.0 (commit `34345ea`): the palette sets Open-WebUI's base colour scale and steps aside for a user's own colours; the Surfaces tab drives every transparency, so the Sidebar Transparency and Overlay Transparency valves are gone; Allow Personal Themes and Auto Sync start on; the side chats' message input is styled; the pictures behind pages and chats stay where they belong when Open-WebUI opens a page as a tab. Live reload was already owpp's copy of the same version.
- Open-WebUI v0.13.5: OLED lasts past the next page load (Open-WebUI's `theme` stays `dark`, and OLED is kept under `owui_tdp_oled`), in the page-side scripts, kept as `adapt/open-webui-0.13.5.patch` (README: What changed for Open-WebUI v0.13.5).

## 1.22.0

- Adapted from Theme Designer Pro 1.22.0 and its Launcher 2.1.2 by G30, broken into the plugin format: the designer page, the bootloader and the admin scripts as templates, the routes behind owpp's sign-in guard, the events as `@on` handlers, the Launcher's signed link in `shared.py`. Every response it shares with the original is the same (README: How owpp broke it down).
