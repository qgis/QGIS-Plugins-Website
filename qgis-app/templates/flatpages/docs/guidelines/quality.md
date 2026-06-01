# Plugin Quality

A well-maintained plugin builds user trust and is more likely to pass the approval process
quickly. These guidelines cover ongoing maintenance, code organisation, and the automated
security scanning applied to all uploaded packages.

---

## Maintaining your plugin page

- Keep the version, changelog, and description up to date with each release. Annotate
  versions with meaningful version numbers and include a changelog so users understand
  what has changed.
- Respond to issues raised in your tracker — active maintenance signals to users and
  approvers that the plugin is supported.
- Ensure the source repository is publicly accessible and contains both a `README`
  and a `LICENSE` file.
- Verify that the source code uploaded as a ZIP matches the **Code repository**
  link declared in `metadata.txt`.

## Security scanning

Every plugin version uploaded to this repository is automatically scanned for security issues
and code quality. Review your results after each upload and address any findings before
releasing to users. See the [Security Scanning](/docs/security-scanning) page for details.

---

## Recommendations

- Write code comments in English to make it easier for others to contribute.
- Provide a minimal dataset for testing purposes.
- Place the plugin in the appropriate QGIS menu (Vector, Raster, Web, Database).
- Before publishing a new plugin, check whether it duplicates existing functionality and
  explore collaboration possibilities with existing plugin authors.
- Make the plugin work on all supported platforms (Windows, Linux, macOS). If it only works
  on selected platforms, state this clearly in the description.
- Mention any requirements, dependencies, and restrictions in the description. For example:
  if the plugin requires separately installed software, a user account, or only covers
  certain countries or regions.
- If some dependencies are not available in OSGeo4W Python, provide installation instructions
  for Windows users, e.g. referencing a guide such as
  [Installing Python packages in QGIS 3 (for Windows)](https://landscapearchaeology.org/2018/installing-python-packages-in-qgis-3-for-windows/).

---

## Tips and Tricks

The tips below expand on the
[Tips and Tricks section of the PyQGIS Developer Cookbook ↗](https://docs.qgis.org/latest/en/docs/pyqgis_developer_cookbook/plugins/plugins.html#tips-and-tricks).

### Keep your source repository clean

- No generated files left in the repository (`ui_*.py`, `resources_rc.py`, generated help files…).
- No `__MACOSX`, `.git`, `__pycache__` or other hidden directories.
- Good code organisation using subfolders.
- Code comments present throughout.
- PEP 8 and Python/QGIS guidelines compliance.
- A `README` file and a `LICENSE` file at the root.

### Use QGIS network and UI components

- Use [QgsNetworkAccessManager](https://qgis.org/pyqgis/latest/core/QgsNetworkAccessManager.html)
  instead of `urllib2`, `requests`, or similar libraries, which often fail to use the correct
  proxy settings.
- Use QGIS widgets such as
  [QgsMapLayerComboBox](https://qgis.org/pyqgis/latest/gui/QgsMapLayerComboBox.html)
  for layer selection dropdowns. Check the
  [full list of QGIS GUI widgets](https://qgis.org/pyqgis/latest/gui/index.html)
  for available components.

### Use a plugin template

Starting from a template ensures a well-structured project from day one:

- [QGIS Plugin Templater GUI](/plugins/qgis_plugin_templater_gui/) — a graphical plugin
  generator available in the repository.
- [QGIS Minimal Plugin](https://github.com/wonder-sk/qgis-minimal-plugin) — the simplest
  possible starting point.
- For developers familiar with git workflows, consider a
  [Cookiecutter](https://cookiecutter.readthedocs.io/) template:
    - [QGIS Plugin Templater](https://oslandia.gitlab.io/qgis/template-qgis-plugin/)
      (powers the GUI plugin listed above)
    - [Cookiecutter QGIS Plugin](https://github.com/GispoCoding/cookiecutter-qgis-plugin)

For more guidance on setting up a well-structured plugin project, see
[Set up plugin file structure ↗](https://docs.qgis.org/latest/en/docs/pyqgis_developer_cookbook/plugins/plugins.html#set-up-plugin-file-structure)
in the PyQGIS Developer Cookbook. Use the
[Plugin Reloader ↗](https://docs.qgis.org/latest/en/docs/pyqgis_developer_cookbook/plugins/plugins.html#plugin-reloader)
during development, and the
[qgis-plugin-ci tool ↗](https://docs.qgis.org/latest/en/docs/pyqgis_developer_cookbook/plugins/plugins.html#automate-packaging-release-and-translation-with-qgis-plugin-ci)
to automate packaging, releasing, and translating your plugin.

---

## Embedded binaries

Pre-compiled binaries are **explicitly prohibited** in plugins submitted to this repository.
Plugins that contain binaries will not be approved:

- Pre-compiled files (`.dll`, `.so`, `.dylib`, `.exe`, `.pyd`) must **not** be included in the
  plugin ZIP. There are no exceptions based on necessity or convenience — if it cannot be
  distributed through a standard package manager, it cannot be bundled in the plugin ZIP.
- If you believe your plugin genuinely cannot function without a compiled binary, you must
  post to the
  [qgis-developer mailing list](https://lists.osgeo.org/mailman/listinfo/qgis-developer)
  to state your case before uploading.
  An exception can only be granted after explicit approval through that process.
- If an exception is granted, the full source code for the binary must be publicly available
  and build instructions must be provided in the repository.
  Proprietary binary blobs are never accepted under any circumstances.
- Compiled Python bytecode (`.pyc`) should not be included — it is generated automatically
  on import.
- Declare any compiled component in the `about` field so users and reviewers are aware of it.

---

## Cross-platform support

QGIS runs on Windows, macOS, and Linux. Plugins should aim to work on all three platforms:

- Test your plugin on all supported platforms before each release, or clearly document any
  known platform limitations in the `about` field.
- Use `os.path.join()` or `pathlib.Path` for file paths — never hard-code forward or
  backslashes.
- Avoid dependencies on platform-specific system libraries or CLI tools unless you provide
  clear installation instructions for each platform.
- If a compiled extension or binary dependency is only available for one platform, mark the
  plugin's supported platforms explicitly in the metadata.

---

## Advertising and data collection

Plugins distributed through this repository must not use their position in the QGIS Plugin
Manager as an advertising vehicle:

- No in-plugin advertising banners, pop-up promotions, or marketing messages unrelated to
  the plugin's stated function.
- No telemetry, usage analytics, error reporting, or any other data collection without
  **explicit opt-in consent** from the user, with a clear description of what is collected
  and where it is sent.
- No automatic update mechanisms that bypass the QGIS Plugin Manager.
- Commercial integrations (e.g. plugins that connect to a paid service) are permitted, but
  the commercial nature must be disclosed in the metadata as described in the
  [Requirements](/docs/guidelines/requirements) guidelines.
  The plugin itself must remain free to download.
