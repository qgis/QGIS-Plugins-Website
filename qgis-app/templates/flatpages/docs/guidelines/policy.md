# Repository Policy

These policies govern the relationship between plugin authors, users, and the QGIS Plugin
Repository team. They exist to keep the repository safe, neutral, and trustworthy for the
entire QGIS community.

---

## Plugin removal and banning

The QGIS Plugin Repository team reserves the right to remove, disable, or ban any plugin at
any time if it:

- Violates any of the guidelines described in this documentation.
- Contains malware, spyware, or any code that harms users or their systems.
- Poses a security risk that the author is unwilling or unable to address promptly.
- Contains undisclosed data collection or advertising (see [Plugin Quality](/docs/guidelines/quality)).
- Is clearly abandoned and poses a risk to users running it on newer QGIS versions.
- Has been published in bad faith or to impersonate another plugin.

Where possible, the team will contact the plugin author before removal and allow reasonable
time to resolve the issue. For serious security violations, immediate removal may occur
without prior notice.

Repeated or severe violations may result in the author's account being suspended from
uploading further plugins.

---

## Dispute procedure

If you believe your plugin has been incorrectly flagged, removed, or rejected, you can raise
a dispute through the following process:

1. Review the rejection or removal notice carefully. The reason given should point to a
   specific guideline; re-read that guideline to ensure you understand what is required.
2. If you believe the decision was made in error, open an issue on the
   [QGIS Plugins Website repository](https://github.com/qgis/QGIS-Plugins-Website/issues)
   or post to the
   [qgis-developer mailing list](https://lists.osgeo.org/mailman/listinfo/qgis-developer).
   Include your plugin name, the stated reason for removal, and the specific point you are
   disputing.
3. The team will review your case and respond. Decisions may be revised if new information
   is provided.

<p class="alert alert-info">
  <strong>Note:</strong> Disputes about subjective editorial judgements (e.g. whether content
  is neutral) may take longer to resolve and are decided by the broader QGIS steering community.
</p>

---

## Renaming plugins

A plugin's internal name (the folder name used in the ZIP, which forms part of the repository
URL) is **permanent** and cannot be changed after the first upload. This ensures stable links
in documentation, tutorials, and scripts that reference the plugin by name.

For information on changing the plugin display name, see the
[FAQ — How do I rename an existing plugin?](/docs/faq#rename)

---

## Code of conduct

All plugin authors and contributors are expected to follow the
[QGIS Code of Conduct](https://qgis.org/conduct/).
This applies to:

- Content in the plugin's own repository and issue tracker.
- Interactions on the QGIS mailing lists, Discourse, and chat channels.
- Any community space where you represent your plugin or the QGIS project.

Reports of code-of-conduct violations can be submitted to the
[QGIS Project Steering Committee](mailto:psc@qgis.org).

---

## Politics and contentious topics

The QGIS project is an international community that deliberately avoids taking political,
religious, or partisan stances. Plugins in the repository must reflect this neutrality:

- Plugins must not promote political parties, electoral campaigns, religious organisations,
  or partisan advocacy of any kind.
- Cartographic and analytical tools that handle contested territorial boundaries, place names,
  or geopolitical situations must present data as neutrally as possible, referencing
  authoritative international sources (e.g. UN, ISO 3166) rather than adopting a particular
  national position.
- Plugins dealing with sensitive socio-economic or environmental data should present results
  neutrally and let users draw their own conclusions.
- Plugins with a legitimate professional or research purpose in politically sensitive domains
  (e.g. conflict mapping, election data tools) are welcome, provided the plugin itself
  remains a neutral tool and does not advocate a particular position.

If you are uncertain whether your plugin's subject matter is suitable for the repository,
open a discussion on the
[qgis-developer mailing list](https://lists.osgeo.org/mailman/listinfo/qgis-developer)
before uploading.
