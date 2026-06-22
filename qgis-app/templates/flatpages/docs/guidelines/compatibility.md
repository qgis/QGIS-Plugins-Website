# Version Compatibility

QGIS version compatibility is determined by the `qgisMinimumVersion` and
`qgisMaximumVersion` fields in `metadata.txt`. Declaring these accurately ensures your plugin
appears in the correct filter lists inside the Plugin Manager and avoids compatibility warnings
for users. See the
[metadata.txt reference ↗](https://docs.qgis.org/latest/en/docs/pyqgis_developer_cookbook/plugins/plugins.html#metadata-txt)
for all version-related fields.

---

## How version ranges work

- If `qgisMaximumVersion` is omitted, compatibility is assumed only up to the end of the
  major version set by `qgisMinimumVersion`.
- To mark a QGIS 3 plugin as also supporting QGIS 4, keep `qgisMinimumVersion=3.x` and add
  `qgisMaximumVersion=4.99`. This makes the plugin appear in the
  [QGIS 4 Ready Plugins](/plugins/new_qgis_ready/) list.
- QGIS 4 uses Qt 6, which requires code changes in plugins. Before declaring QGIS 4
  compatibility, review the
  [Plugin migration to Qt5 and Qt6](https://github.com/qgis/QGIS/wiki/Plugin-migration-to-be-compatible-with-Qt5-and-Qt6)
  guide.

## Examples

- `qgisMinimumVersion=3.22`, `qgisMaximumVersion=4.99` — listed for QGIS 3.22+ **and** QGIS 4.x
- `qgisMinimumVersion=4.0`, `qgisMaximumVersion=4.99` — listed for QGIS 4.x only
- `qgisMinimumVersion=3.22` (no `qgisMaximumVersion`) — QGIS 3.x only; not listed for QGIS 4

For full instructions on migrating your plugin's code to QGIS 4, see the
[Migrate to QGIS 4](/docs/migrate-qgis4) page.
