# Requirements

Your plugin's metadata is the first — and often only — thing a user reads before deciding
whether to install it. It must give an accurate picture of what the plugin does, what it
requires, and how to get support.

---

## Required metadata fields

All plugins must include the following in `metadata.txt`:

- **description** — a short, one-line English summary of what the plugin does.
  This is shown directly in the Plugin Manager list.
- **about** — a fuller explanation of the plugin's purpose, features, and any requirements.
  If the plugin depends on external software or a service, this must be stated here (see below).
- **homepage** — a link to a page describing plugin usage (README, wiki, or a dedicated web
  page). Simple repository root or download links are not acceptable.
- **repository** — a link to the publicly accessible source code. The repository must not
  contain zipped copies of the plugin.
- **tracker** — a link to the issue tracker where users can report bugs and request features.
- **license** — a recognised open-source license (see below for which licenses are accepted).
  A `LICENSE` file must be present in the repository
  ([more information about licensing](http://blog.qgis.org/2016/05/29/licensing-requirements-for-qgis-plugins/)).

The plugin package size must not exceed **25 MB**.

For the complete list of supported fields and their syntax, see the
[metadata.txt reference in the PyQGIS Developer Cookbook ↗](https://docs.qgis.org/latest/en/docs/pyqgis_developer_cookbook/plugins/plugins.html#metadata-txt).

---

## Accepted licenses

All plugins in the repository must be published under an
[OSI-approved open-source license](https://opensource.org/licenses).
Proprietary, source-available, or "non-commercial" licenses are not accepted.
Because QGIS itself is licensed under the
[GPL v2 or later](https://www.gnu.org/licenses/gpl-2.0.html),
we strongly recommend using a GPL-compatible license.

Commonly used licenses that are accepted:

- **GPL v2+** and **GPL v3** — recommended; directly compatible with QGIS.
- **LGPL v2.1** and **LGPL v3** — accepted.
- **AGPL v3** — accepted; be aware of its network-use implications.
- **MIT** — accepted; permissive and widely used.
- **BSD 2-Clause** and **BSD 3-Clause** — accepted.
- **Apache 2.0** — accepted.

<p class="alert alert-info">
  <strong>Note:</strong> Creative Commons licenses (e.g. CC-BY, CC-SA) are designed for
  creative works, not software. They are not appropriate for plugin code and will not be
  accepted.
</p>

---

## Language requirements

The `name`, `description`, and `about` fields in `metadata.txt` must be written in
**English**. This ensures all users can understand what a plugin does before installing it,
and allows the approval team to review the content.

The plugin's own user interface may be in any language. Providing translations is encouraged
but not required. To learn how to add translations to your plugin, see the
[Translating plugins section in the PyQGIS Developer Cookbook ↗](https://docs.qgis.org/latest/en/docs/pyqgis_developer_cookbook/plugins/plugins.html#translating-plugins).

---

## Description and About fields

- Keep the `description` field concise and keyword-rich — it is the first thing users see
  when browsing the Plugin Manager.
- Use the `about` field for a complete explanation including supported platforms, spatial
  coverage if limited, and any external dependencies. The field supports multiple lines.
- Respect the licenses of any libraries or resources your plugin uses and mention them in the
  description if relevant.
- The plugin and folder name should not repeat the word *plugin*.
- Do not rename the plugin title just because it has been upgraded to a newer QGIS version.

---

## Plugins with external software or commercial integrations

Plugins that act as front-ends for commercial software, web services, or proprietary platforms
are permitted in the repository, provided:

- The dependency is disclosed in the `about` field of `metadata.txt`, in the README or
  homepage, and in the plugin's own UI when the dependency is not detected.
- Any cost, licensing requirement, or registration step is stated explicitly — not hidden
  behind a link.
- The plugin itself remains free of charge to download and install from this repository.

Example of a transparent `about` entry:

> *"This plugin provides a QGIS interface for district energy modelling workflows.
> Basic project setup is available without additional software.
> Running detailed simulations requires IDA Districts (commercial software;
> a free trial is available at example.com)."*

<p class="alert alert-info">
  <strong>Note:</strong> The approval team specifically reviews external-dependency disclosures.
  Incomplete or misleading descriptions are the most common reason an approval is delayed.
</p>

---

## Dependency management

If your plugin depends on Python packages not included in a standard QGIS installation,
you must declare and manage those dependencies explicitly:

- List all required packages clearly in the `about` field and in the plugin README.
- Do not bundle large third-party libraries directly inside the plugin ZIP. Instead, prompt
  the user to install them (e.g. via `pip`) or use the QGIS Plugin Manager's dependency
  installer if available for your QGIS version.
- For Windows users, provide instructions for packages not available through OSGeo4W — see the
  [Installing Python packages in QGIS 3 guide](https://landscapearchaeology.org/2018/installing-python-packages-in-qgis-3-for-windows/)
  as an example.
- If you ship a `requirements.txt` in the repository, keep it accurate and version-pinned
  where stability matters.
- Any system-level dependency (e.g. GDAL version, external CLI tools) must be stated in the
  `about` field. The plugin must fail gracefully with a clear error message when a dependency
  is missing, rather than crashing silently.

The `plugin_dependencies` field in `metadata.txt` lets you declare other QGIS plugins that
should be installed automatically — see the
[metadata.txt reference ↗](https://docs.qgis.org/latest/en/docs/pyqgis_developer_cookbook/plugins/plugins.html#metadata-txt)
for the syntax.

---

## Tags, icon, and links

- Choose specific **tags** that reflect the plugin's domain and workflow
  (e.g. *energy, urban planning, simulation, hydrology*). Tags are the primary way users
  discover plugins through search in the Plugin Manager.
- Provide a recognisable **icon** — it appears at small sizes in the Plugin Manager list.
- Keep the **homepage**, **repository**, and **tracker** links valid and up to date.
  The homepage should include screenshots and quick-start instructions.

Refer to the
[metadata.txt reference ↗](https://docs.qgis.org/latest/en/docs/pyqgis_developer_cookbook/plugins/plugins.html#metadata-txt)
for the complete list of accepted field names including `tags`, `icon`, and optional link fields.
