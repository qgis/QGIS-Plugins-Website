# Release communication templates

Reusable templates for pre announcing an **upcoming** planned release of the
QGIS Plugins Website (plugins.qgis.org). These go out **before** the release
ships, so the community knows what is coming and plugin developers can review or
test while there is still time to adjust. Copy the relevant block, replace every
`{{PLACEHOLDER}}`, and publish.

There are three channels:

1. **Blog post** with the full changelog.
2. **Email** to plugin developers pointing at the blog post.
3. **QGIS Feed** entry (under 500 characters) whose title links to the blog post.


---

## 1. Blog post (full changelog)

```markdown
---
title: "Coming soon: QGIS Plugins Website {{VERSION}}"
date: {{ANNOUNCEMENT_DATE}}
author: {{AUTHOR}}
tags: [announcement, upcoming-release, plugins.qgis.org]
---

# Coming soon: QGIS Plugins Website {{VERSION}}

We are preparing version **{{VERSION}}** of the QGIS Plugins Website
(plugins.qgis.org), a planned milestone release scheduled for
**{{RELEASE_DATE}}**. Below is a summary of what is coming and how it may affect
plugin developers, so you can review ahead of time.

## Highlights

{{ONE_OR_TWO_SENTENCE_OVERVIEW_OF_THE_MARQUEE_CHANGES}}

## What is changing in {{VERSION}}

The items below are planned for this release and are tracked
in the changelog until {{VERSION}} ships.

### Added
* {{NEW_FEATURE_1}}
* {{NEW_FEATURE_2}}

### Changed
* {{CHANGE_1}}
* {{CHANGE_2}}

### Fixed
* {{BUGFIX_1}}
* {{BUGFIX_2}}

### Security
* {{SECURITY_ITEM_IF_ANY}}

## What this means for plugin developers

{{ANYTHING_DEVELOPERS_SHOULD_PREPARE_OR_NONE}}
For most developers no action is needed. If you maintain a plugin, please
review the planned changes above before {{RELEASE_DATE}} to confirm nothing
affects your publishing workflow, and tell us about any concerns while there is
still time to adjust the release. For that, please raise an issue at 
https://github.com/qgis/QGIS-Plugins-Website/issues.

## When and where

Version **{{VERSION}}** is planned for **{{RELEASE_DATE}}** and will be deployed
as the pinned image `qgis/qgis-plugins-uwsgi:{{VERSION}}`. You can follow
progress on the [{{VERSION}} milestone]({{MILESTONE_URL}}). The work landing in
this release is listed under "Unreleased" in [CHANGELOG.md]({{CHANGELOG_URL}}),
and the final release notes will be published on
[GitHub]({{GITHUB_RELEASE_URL}}) once it ships.

## Thanks

Thank you to everyone contributing issues, code, and review for the work going
into this release: {{CONTRIBUTORS}}.

```

---

## 2. Email to plugin developers

```text
Subject: Coming on {{RELEASE_DATE}}: QGIS Plugins Website {{VERSION}}

Hello {{FIRST_NAME_OR_Plugin_developer}},

We are getting ready to release version {{VERSION}} of the QGIS Plugins Website
(plugins.qgis.org), planned for {{RELEASE_DATE}}. Here is a heads up on what is
coming.

In short:
  * {{HIGHLIGHT_1}}
  * {{HIGHLIGHT_2}}
  * {{HIGHLIGHT_3}}

{{IF_ACTION_REQUIRED: One thing to prepare before {{RELEASE_DATE}}: }}
{{ACTION_REQUIRED_SUMMARY_OR_No action is needed on your part.}}

The full preview, planned changes, and screenshots are on our blog:
  {{BLOG_URL}}

If anything here is a concern, please raise an issue at 
https://github.com/qgis/QGIS-Plugins-Website/issues before {{RELEASE_DATE}} while we can still
adjust. Thank you for being part of the QGIS plugin community.

Warm regards,
{{SENDER_NAME}}
The QGIS Plugins Website team

```

---

## 3. QGIS Feed entry (under 500 characters)

The feed entry's title is the clickable link. Set the entry's external URL
field to `{{BLOG_URL}}` so the title itself navigates to the blog post.

**Title (links to blog):**

```
Coming soon: QGIS Plugins Website {{VERSION}}
```

**Body:**

```
A planned update to the plugins.qgis.org website is coming on {{RELEASE_DATE}}. Highlights of version {{VERSION}}: {{HIGHLIGHT_1}}, {{HIGHLIGHT_2}}, and {{HIGHLIGHT_3}}. Plugin developers can preview the planned changes now to confirm nothing affects publishing. For most, no action is needed. Read the full preview and details on our blog by clicking the title above. Thank you for being part of the QGIS community.
```
