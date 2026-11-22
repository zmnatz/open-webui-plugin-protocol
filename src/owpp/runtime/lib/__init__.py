# The built-in libraries (docs/libraries.md). Plugins import them from owpp.lib; the bundler
# inlines each one a plugin needs and removes the imports.
#
# shared_assets.py and live_reload.py are Classic298's Shared Assets Protocol, kept byte-identical
# (https://github.com/Classic298/open-webui-plugins/tree/main/shared-assets-protocol), so they
# are not given imports: live_reload uses shared_assets' names and the plugin's `register` as they
# are in one bundle, and imports open_webui at its top. Plugins reach them through the assets
# library, which imports shared_assets (it imports on its own) and only type-checks live_reload.
# To upgrade them, replace both files with the upstream ones, unchanged, and run the tests:
# test_bundle checks the bundle's ASSET_IMPL_VERSION and the order, and test_assets serves the
# fragments through the real shared route. Then note the new version in docs/libraries.md.
