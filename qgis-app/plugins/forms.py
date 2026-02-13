# i18n
import re

from django import forms
from django.forms import ModelForm, ValidationError
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from plugins.models import (
    Plugin,
    PluginOutstandingToken,
    PluginVersion,
)
from plugins.validator import validator
from taggit.forms import TagField


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data]
        else:
            result = single_file_clean(data, initial)
        return result


def _clean_tags(tags):
    """Return a stripped and cleaned tag list, empty tags are deleted"""
    if tags:
        _tags = []
        for t in tags.split(","):
            if t.strip():
                _tags.append(t.strip())
        return ",".join(_tags)
    return None


class PluginForm(ModelForm):
    """
    Form for plugin editing
    """

    required_css_class = "required"
    tags = TagField(required=False)

    class Meta:
        model = Plugin
        fields = (
            "description",
            "about",
            "author",
            "email",
            "icon",
            "deprecated",
            "homepage",
            "tracker",
            "repository",
            "owners",
            "maintainer",
            "display_created_by",
            "tags",
            "server",
        )

    def __init__(self, *args, **kwargs):
        super(PluginForm, self).__init__(*args, **kwargs)
        self.fields["owners"].label = "Collaborators"

        choices = (
            (
                self.instance.created_by.pk,
                self.instance.created_by.username + " (Plugin creator)",
            ),
        )
        for owner in self.instance.owners.exclude(pk=self.instance.created_by.pk):
            choices += ((owner.pk, owner.username + " (Collaborator)"),)

        self.fields["maintainer"].choices = choices
        self.fields["maintainer"].label = "Maintainer"

    def clean(self):
        """
        Check author
        """
        if self.cleaned_data.get("author") and not re.match(
            r"^[^/]+$", self.cleaned_data.get("author")
        ):
            raise ValidationError(_("Author name cannot contain slashes."))
        return super(PluginForm, self).clean()


class PluginVersionForm(ModelForm):
    """
    Form for version upload on existing plugins
    """

    required_css_class = "required"
    package = forms.FileField(
        label=_("Plugin Package"),
        help_text=_("Select the zipped plugin file (maximum size: 25MB)."),
    )
    changelog = forms.fields.CharField(
        label=_("Changelog"),
        required=False,
        help_text=_(
            "Insert here a short description of the changes that have been made in this version. This field is not mandatory and it is automatically filled from the metadata.txt file."
        ),
        widget=forms.Textarea,
    )

    def __init__(self, *args, **kwargs):
        kwargs.pop("is_trusted")
        super(PluginVersionForm, self).__init__(*args, **kwargs)
        # FIXME: check why this is not working correctly anymore
        #        now "approved" is removed from the form (see Meta)
        # instance = getattr(self, 'instance', None)
        # if instance and not is_trusted:
        #    self.fields['approved'].initial = False
        #    self.fields['approved'].widget.attrs = {'disabled':'disabled'}
        #    instance.approved = False

    class Meta:
        model = PluginVersion
        exclude = (
            "created_by",
            "plugin",
            "approved",
            "version",
            "min_qg_version",
            "max_qg_version",
        )
        fields = ("package", "changelog")

    def clean(self):
        """
        Only read package if uploaded
        """
        # Override package
        changelog = self.cleaned_data.get("changelog")

        if self.files:
            package = self.cleaned_data.get("package")
            try:
                cleaned_data = validator(package)
                self.cleaned_data.update(cleaned_data)
            except ValidationError as e:
                msg = _(
                    "There were errors reading plugin package (please check also your plugin's metadata).<br />"
                )
                raise ValidationError(
                    mark_safe("%s %s" % (msg, "<br />".join(e.messages)))
                )
            # Populate instance
            self.instance.min_qg_version = self.cleaned_data.get("qgisMinimumVersion")
            self.instance.max_qg_version = self.cleaned_data.get("qgisMaximumVersion")
            self.instance.version = PluginVersion.clean_version(
                self.cleaned_data.get("version")
            )
            self.instance.server = self.cleaned_data.get("server")

            # Check plugin folder name
            if (
                self.cleaned_data.get("package_name")
                and self.cleaned_data.get("package_name")
                != self.instance.plugin.package_name
            ):
                raise ValidationError(
                    _(
                        "Plugin folder name mismatch: the plugin main folder name in the compressed file (%s) is different from the original plugin package name (%s)."
                    )
                    % (
                        self.cleaned_data.get("package_name"),
                        self.instance.plugin.package_name,
                    )
                )
        # Also set changelog from metadata
        if changelog:
            self.cleaned_data["changelog"] = changelog
        # Clean tags
        self.cleaned_data["tags"] = _clean_tags(self.cleaned_data.get("tags", None))
        self.instance.changelog = self.cleaned_data.get("changelog")
        if "experimental" in self.cleaned_data:
            self.instance.experimental = self.cleaned_data.get("experimental")
        if "supportsQt6" in self.cleaned_data:
            self.instance.supports_qt6 = self.cleaned_data.get("supportsQt6")
        return super(PluginVersionForm, self).clean()


class PluginCreateForm(forms.Form):
    """
    Form for creating an empty plugin (no versions yet).
    Minimal fields - the rest will be populated from metadata.txt on first upload.
    """

    required_css_class = "required"
    name = forms.CharField(
        label=_("Plugin name"),
        help_text=_("A display name for your plugin. It must be unique."),
        max_length=256,
    )
    package_name = forms.CharField(
        label=_("Package name"),
        help_text=_(
            "This must be the main plugin folder name inside your zip file. Use only ASCII letters, digits, '-' or '_'. This cannot be changed later."
        ),
        max_length=256,
    )

    def clean_package_name(self):
        package_name = self.cleaned_data.get("package_name", "").strip()
        if not re.match(r"^[A-Za-z][A-Za-z0-9-_]+$", package_name):
            raise ValidationError(
                _(
                    "Package name must start with a letter and can contain only ASCII letters, digits, '-' or '_'."
                )
            )
        existing = Plugin.objects.filter(package_name__iexact=package_name).first()
        if existing:
            raise ValidationError(
                _("A plugin with a similar package name (%s) already exists.")
                % existing.package_name
            )
        return package_name

    def clean_name(self):
        name = self.cleaned_data.get("name", "").strip()
        existing = Plugin.objects.filter(name__iexact=name).first()
        if existing:
            raise ValidationError(
                _("A plugin with a similar name (%s) already exists.") % existing.name
            )
        return name

    def save(self, created_by, commit=True):
        plugin = Plugin()
        # Set all required fields first
        plugin.created_by = created_by
        plugin.author = created_by.get_full_name() or created_by.username
        plugin.email = created_by.email or "noreply@example.com"
        plugin.description = "Placeholder - will be updated on first version upload"
        plugin.package_name = self.cleaned_data.get("package_name")
        plugin.name = self.cleaned_data.get("name")

        if commit:
            # Skip model validation since we already validated in the form
            plugin.save()
        return plugin


class PackageUploadForm(forms.Form):
    """
    Single step upload for new plugins
    """

    package = forms.FileField(
        label=_("Plugin Package"),
        help_text=_("Select the zipped plugin file (maximum size: 25MB)."),
    )

    def clean(self):
        clean_data = super(PackageUploadForm, self).clean()
        return clean_data

    def clean_package(self):
        """
        Populates cleaned_data with metadata from the zip package
        """
        package = self.cleaned_data.get("package")
        try:
            self.cleaned_data.update(validator(package, is_new=True))
        except ValidationError as e:
            msg = _(
                "There were errors reading plugin package (please check also your plugin's metadata)."
            )
            raise ValidationError(mark_safe("%s %s" % (msg, ",".join(e.messages))))
        # Disabled: now the PackageUploadForm also accepts updates
        # if Plugin.objects.filter(package_name = self.cleaned_data['package_name']).count():
        #    raise ValidationError(_('A plugin with this package name (%s) already exists. To update an existing plugin, you should open the plugin\'s details view and add a new version from there.') % self.cleaned_data['package_name'])

        # if Plugin.objects.filter(name = self.cleaned_data['name']).count():
        #    raise ValidationError(_('A plugin with this name (%s) already exists.') % self.cleaned_data['name'])
        self.cleaned_data["version"] = PluginVersion.clean_version(
            self.cleaned_data["version"]
        )
        # Checks for version
        if Plugin.objects.filter(
            package_name=self.cleaned_data["package_name"],
            pluginversion__version=self.cleaned_data["version"],
        ).count():
            raise ValidationError(
                _(
                    "A plugin with this name (%s) and version number (%s) already exists."
                )
                % (self.cleaned_data["name"], self.cleaned_data["version"])
            )
        # Clean tags
        self.cleaned_data["tags"] = _clean_tags(self.cleaned_data.get("tags", None))
        return package


class VersionFeedbackForm(forms.Form):
    """Feedback for a plugin version"""

    feedback = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "placeholder": _(
                    "Please provide clear feedback as a task. \n"
                    "You can create multiple tasks with '- [ ]'.\n"
                    "e.g:\n"
                    "- [ ] first task\n"
                    "- [ ] second task"
                ),
                "rows": "5",
                "class": "textarea is-fullwidth",
            }
        )
    )

    images = MultipleFileField(
        required=False,
        widget=MultipleFileInput(
            attrs={"multiple": True, "accept": "image/*", "class": "file-input"}
        ),
        help_text=_("Upload images or GIFs to support your feedback (optional)"),
    )

    def clean_images(self):
        images = self.cleaned_data.get("images")
        if images:
            # Handle both single file and list of files
            if not isinstance(images, list):
                images = [images] if images else []

            for image in images:
                # Validate file type
                if not image.content_type.startswith("image/"):
                    raise forms.ValidationError(_("Only image files are allowed."))
                # Validate file size (max 5MB)
                if image.size > 5 * 1024 * 1024:
                    raise forms.ValidationError(
                        _("Image file size must be less than 5MB.")
                    )
        return images

    def clean(self):
        super().clean()
        feedback = self.cleaned_data.get("feedback")

        if feedback:
            lines: list = feedback.split("\n")
            bullet_points: list = [
                line[6:].strip() for line in lines if line.strip().startswith("- [ ]")
            ]
            has_bullet_point = len(bullet_points) >= 1
            tasks: list = bullet_points if has_bullet_point else [feedback]
            self.cleaned_data["tasks"] = tasks

        return self.cleaned_data


class PluginTokenForm(ModelForm):
    """
    Form for token description editing
    """

    class Meta:
        model = PluginOutstandingToken
        fields = ("description",)
