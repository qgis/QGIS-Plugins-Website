# -*- coding: utf-8 -*-

import datetime
import os
import re
import secrets

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.models import Count, F, OuterRef, Subquery
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from djangoratings.fields import AnonymousRatingField
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from taggit_autosuggest.managers import TaggableManager

PLUGINS_STORAGE_PATH = getattr(settings, "PLUGINS_STORAGE_PATH", "packages/%Y")
PLUGINS_FRESH_DAYS = getattr(settings, "PLUGINS_FRESH_DAYS", 30)


# Used in Version fields to transform DB value back to human readable string
# Allows "-" for processing plugin
VERSION_RE = r"(^|(?<=\.))0+(?!(\.|$|-))|\.#+"


class BasePluginManager(models.Manager):
    """
    Adds a score
    * average_vote provides a simple average rating.
    * latest_version_date fetches the date of the
    most recent approved plugin version.
    * weighted_rating uses the Bayesian Average formula
    to provide a more balanced rating that mitigates the effect of low vote counts.

    Includes soft-deleted plugins so they remain visible in listings until
    permanently deleted.
    """

    def get_queryset(self):
        return (
            super(BasePluginManager, self)
            .get_queryset()
            .extra(
                select={
                    "average_vote": "rating_score / (rating_votes + 0.001)",
                    "latest_version_date": (
                        "SELECT created_on FROM plugins_pluginversion WHERE "
                        "plugins_pluginversion.plugin_id = plugins_plugin.id "
                        "AND approved = TRUE "
                        "ORDER BY created_on DESC LIMIT 1"
                    ),
                    "weighted_rating": (
                        "((rating_votes::FLOAT / (rating_votes + 5)) * "
                        "(rating_score::FLOAT / (rating_votes + 0.001))) + "
                        "((5::FLOAT / (rating_votes + 5)) * 3)"
                    ),
                }
            )
        )


class ApprovedPlugins(BasePluginManager):
    """
    Shows only public plugins: i.e. those with
    and with at least one approved version ("stable" or "experimental")
    """

    def get_queryset(self):
        return (
            super(ApprovedPlugins, self)
            .get_queryset()
            .filter(pluginversion__approved=True)
            .distinct()
        )


class StablePlugins(BasePluginManager):
    """
    Shows only public plugins: i.e. those with "approved" flag set
    and with one "stable" version
    """

    def get_queryset(self):
        return (
            super(StablePlugins, self)
            .get_queryset()
            .filter(pluginversion__approved=True, pluginversion__experimental=False)
            .distinct()
        )


class ExperimentalPlugins(BasePluginManager):
    """
    Shows only public plugins: i.e. those with "approved" flag set
    and with one "experimental" version
    """

    def get_queryset(self):
        return (
            super(ExperimentalPlugins, self)
            .get_queryset()
            .filter(pluginversion__approved=True, pluginversion__experimental=True)
            .distinct()
        )


class NewQgisMajorVersionReadyPlugins(BasePluginManager):
    """
    Shows only public plugins: i.e. those with "approved" flag set
    and with one version that is compatible with the new QGIS major version.
    This is determined by checking if the max_qg_version is greater
    than or equal to the new QGIS major version.
    This manager filters out deprecated plugins as well.
    """

    def get_queryset(self):
        return (
            super(NewQgisMajorVersionReadyPlugins, self)
            .get_queryset()
            .filter(
                pluginversion__approved=True,
                pluginversion__max_qg_version__gte=f"{settings.NEW_QGIS_MAJOR_VERSION}.0",
            )
            .distinct()
            .order_by("-created_on")
        )


class FeaturedPlugins(BasePluginManager):
    """
    Shows only public featured stable plugins: i.e. those with "approved" flag set
    and "featured" flag set
    """

    def get_queryset(self):
        return (
            super(FeaturedPlugins, self)
            .get_queryset()
            .filter(pluginversion__approved=True, featured=True)
            .order_by("-created_on")
            .distinct()
        )


class FreshPlugins(BasePluginManager):
    """
    Shows only approved plugins: i.e. those with "approved" version flag set
    and created less than "days" ago.
    """

    def __init__(self, days=PLUGINS_FRESH_DAYS, *args, **kwargs):
        self.days = days
        return super(FreshPlugins, self).__init__(*args, **kwargs)

    def get_queryset(self):
        return (
            super(FreshPlugins, self)
            .get_queryset()
            .filter(
                deprecated=False,
                pluginversion__approved=True,
                created_on__gte=datetime.datetime.now()
                - datetime.timedelta(days=self.days),
            )
            .order_by("-created_on")
            .distinct()
        )


class LatestPlugins(BasePluginManager):
    """
    Shows only approved plugins ordered descending by latest_version
    and the latest_version
    """

    def __init__(self, days=PLUGINS_FRESH_DAYS, *args, **kwargs):
        self.days = days
        return super(LatestPlugins, self).__init__(*args, **kwargs)

    def get_queryset(self):
        return (
            super(LatestPlugins, self)
            .get_queryset()
            .filter(
                deprecated=False,
                pluginversion__approved=True,
                pluginversion__created_on__gte=(
                    datetime.datetime.now() - datetime.timedelta(days=self.days)
                ),
            )
            .order_by("-latest_version_date")
            .distinct()
        )


class UnapprovedPlugins(BasePluginManager):
    """
    Shows only unapproved and not deprecated plugins
    """

    def get_queryset(self):
        return (
            super(UnapprovedPlugins, self)
            .get_queryset()
            .filter(pluginversion__approved=False, deprecated=False, is_deleted=False)
            .extra(
                select={
                    "average_vote": "rating_score / (rating_votes + 0.001)",
                    "latest_version_date": (
                        "SELECT created_on FROM plugins_pluginversion WHERE "
                        "plugins_pluginversion.plugin_id = plugins_plugin.id "
                        "ORDER BY created_on DESC LIMIT 1"
                    ),
                    "weighted_rating": (
                        "((rating_votes::FLOAT / (rating_votes + 5)) * "
                        "(rating_score::FLOAT / (rating_votes + 0.001))) + "
                        "((5::FLOAT / (rating_votes + 5)) * 3)"
                    ),
                }
            )
            .distinct()
        )


class DeprecatedPlugins(BasePluginManager):
    """
    Shows only deprecated plugins
    """

    def get_queryset(self):
        return (
            super(DeprecatedPlugins, self)
            .get_queryset()
            .filter(deprecated=True)
            .distinct()
        )


class PopularPlugins(ApprovedPlugins):
    """
    Shows only approved plugins, sort by popularity algorithm
    """

    def get_queryset(self):
        return (
            super(PopularPlugins, self)
            .get_queryset()
            .filter(deprecated=False)
            .extra(
                select={
                    "popularity": "plugins_plugin.downloads * (1 + (rating_score/(rating_votes+0.01)/3))"
                }
            )
            .order_by("-popularity")
            .distinct()
        )


class MostDownloadedPlugins(ApprovedPlugins):
    """
    Shows only approved plugins, sort by downloads
    """

    def get_queryset(self):
        return (
            super(MostDownloadedPlugins, self)
            .get_queryset()
            .filter(deprecated=False)
            .order_by("-downloads")
            .distinct()
        )


class MostVotedPlugins(ApprovedPlugins):
    """
    Shows only approved plugins, sort by vote number
    """

    def get_queryset(self):
        return (
            super(MostVotedPlugins, self)
            .get_queryset()
            .filter(deprecated=False)
            .order_by("-rating_votes")
            .distinct()
        )


class BestRatedPlugins(ApprovedPlugins):
    """
    Shows only approved plugins, sort by vote/number of votes number
    """

    def get_queryset(self):
        return (
            super(BestRatedPlugins, self)
            .get_queryset()
            .filter(deprecated=False)
            .order_by("-weighted_rating")
            .distinct()
        )


class TaggablePlugins(TaggableManager):
    """
    Shows only public plugins: i.e. those with "approved" flag set
    """

    def get_queryset(self):
        return (
            super(TaggablePlugins, self)
            .get_queryset()
            .filter(deprecated=False, pluginversion__approved=True)
            .distinct()
        )


class ServerPlugins(ApprovedPlugins):
    """
    Shows only Server plugins
    """

    def get_queryset(self):
        return super(ServerPlugins, self).get_queryset().filter(server=True).distinct()


class FeedbackCompletedPlugins(models.Manager):
    """
    Show only unapproved plugins with resolved feedbacks
    Excludes soft-deleted plugins.
    """

    def get_queryset(self):
        feedback_count_subquery = (
            PluginVersionFeedback.objects.filter(
                version=OuterRef("pluginversion"), is_completed=True
            )
            .values("version")
            .annotate(completed_count=Count("id"))
            .values("completed_count")
        )

        # Only consider plugins whose latest version is unapproved and all feedbacks are completed
        latest_version_subquery = (
            PluginVersion.objects.filter(plugin=OuterRef("pk"))
            .order_by("-created_on")
            .values("approved")[:1]
        )

        return (
            super(FeedbackCompletedPlugins, self)
            .get_queryset()
            .filter(is_deleted=False)
            .annotate(latest_version_approved=Subquery(latest_version_subquery))
            .filter(latest_version_approved=False, deprecated=False)
            .annotate(
                total_feedback_count=Count("pluginversion__feedback"),
                completed_feedback_count=Subquery(feedback_count_subquery),
            )
            .filter(total_feedback_count=F("completed_feedback_count"))
            .extra(
                select={
                    "average_vote": "rating_score / (rating_votes + 0.001)",
                    "latest_version_date": (
                        "SELECT created_on FROM plugins_pluginversion WHERE "
                        "plugins_pluginversion.plugin_id = plugins_plugin.id "
                        "ORDER BY created_on DESC LIMIT 1"
                    ),
                    "weighted_rating": (
                        "((rating_votes::FLOAT / (rating_votes + 5)) * "
                        "(rating_score::FLOAT / (rating_votes + 0.001))) + "
                        "((5::FLOAT / (rating_votes + 5)) * 3)"
                    ),
                }
            )
            .distinct()
        )


class FeedbackReceivedPlugins(models.Manager):
    """
    Show only unapproved plugins with a pending feedback
    Excludes soft-deleted plugins.
    """

    def get_queryset(self):
        latest_version = (
            PluginVersion.objects.filter(plugin=OuterRef("pk"))
            .order_by("-created_on")
            .values("approved")[:1]
        )

        feedback_count_subquery = (
            PluginVersionFeedback.objects.filter(
                version=OuterRef("pluginversion"), is_completed=False
            )
            .values("version")
            .annotate(received_count=Count("id"))
            .values("received_count")
        )

        return (
            super(FeedbackReceivedPlugins, self)
            .get_queryset()
            .filter(
                deprecated=False,
                is_deleted=False,
            )
            .annotate(
                latest_version_approved=Subquery(latest_version),
                received_feedback_count=Subquery(feedback_count_subquery),
            )
            .filter(
                latest_version_approved=False,
                received_feedback_count__gte=1,
            )
            .extra(
                select={
                    "average_vote": "rating_score / (rating_votes + 0.001)",
                    "latest_version_date": (
                        "SELECT created_on FROM plugins_pluginversion WHERE "
                        "plugins_pluginversion.plugin_id = plugins_plugin.id "
                        "ORDER BY created_on DESC LIMIT 1"
                    ),
                    "weighted_rating": (
                        "((rating_votes::FLOAT / (rating_votes + 5)) * "
                        "(rating_score::FLOAT / (rating_votes + 0.001))) + "
                        "((5::FLOAT / (rating_votes + 5)) * 3)"
                    ),
                }
            )
            .distinct()
        )


class FeedbackPendingPlugins(models.Manager):
    """
    Show only unapproved plugins with a feedback
    Excludes soft-deleted plugins.
    """

    def get_queryset(self):
        latest_version = (
            PluginVersion.objects.filter(plugin=OuterRef("pk"))
            .order_by("-created_on")
            .values("approved")[:1]
        )

        return (
            super(FeedbackPendingPlugins, self)
            .get_queryset()
            .filter(
                deprecated=False,
                is_deleted=False,
            )
            .annotate(
                latest_version_approved=Subquery(latest_version),
                total_feedback_count=Count("pluginversion__feedback"),
            )
            .filter(
                latest_version_approved=False,
                total_feedback_count=0,
            )
            .extra(
                select={
                    "average_vote": "rating_score / (rating_votes + 0.001)",
                    "latest_version_date": (
                        "SELECT created_on FROM plugins_pluginversion WHERE "
                        "plugins_pluginversion.plugin_id = plugins_plugin.id "
                        "ORDER BY created_on DESC LIMIT 1"
                    ),
                    "weighted_rating": (
                        "((rating_votes::FLOAT / (rating_votes + 5)) * "
                        "(rating_score::FLOAT / (rating_votes + 0.001))) + "
                        "((5::FLOAT / (rating_votes + 5)) * 3)"
                    ),
                }
            )
            .distinct()
        )


class Plugin(models.Model):
    """
    Plugins model
    """

    # dates
    created_on = models.DateTimeField(
        _("Created on"), auto_now_add=True, editable=False
    )
    modified_on = models.DateTimeField(_("Modified on"), editable=False)

    # owners
    created_by = models.ForeignKey(
        User,
        verbose_name=_("Created by"),
        related_name="plugins_created_by",
        on_delete=models.CASCADE,
    )

    # maintainer
    maintainer = models.ForeignKey(
        User,
        verbose_name=_("Maintainer"),
        related_name="plugins_maintainer",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )

    display_created_by = models.BooleanField(
        _('Display "Created by" in plugin details'), default=False
    )

    author = models.CharField(
        _("Author"),
        help_text=_(
            "This is the plugin's original author, if different from the uploader, this field will appear in the XML and in the web GUI"
        ),
        max_length=256,
    )
    email = models.EmailField(_("Author email"))
    homepage = models.URLField(_("Plugin homepage"), blank=True, null=True)
    # Support
    repository = models.URLField(_("Code repository"), blank=False, null=True)
    tracker = models.URLField(_("Tracker"), blank=False, null=True)

    owners = models.ManyToManyField(User, blank=True)

    # name, desc etc.
    package_name = models.CharField(
        _("Package Name"),
        help_text=_(
            "This is the plugin's internal name, equals to the main folder name"
        ),
        max_length=256,
        unique=True,
        editable=False,
    )
    name = models.CharField(
        _("Name"), help_text=_("Must be unique"), max_length=256, unique=True
    )

    allow_update_name = models.BooleanField(
        _("Allow update name"),
        help_text=_("Allow name in metadata.txt to update the plugin name"),
        default=False,
    )

    description = models.TextField(_("Description"))
    about = models.TextField(_("About"), blank=False, null=True)

    icon = models.ImageField(
        _("Icon"), blank=True, null=True, upload_to=PLUGINS_STORAGE_PATH
    )

    # downloads (soft trigger from versions)
    downloads = models.IntegerField(_("Downloads"), default=0, editable=False)

    # Flags
    featured = models.BooleanField(_("Featured"), default=False, db_index=True)
    deprecated = models.BooleanField(_("Deprecated"), default=False, db_index=True)

    # Soft delete fields
    is_deleted = models.BooleanField(
        _("Marked for deletion"),
        default=False,
        db_index=True,
        help_text=_(
            "Plugin marked for deletion. Will be permanently deleted after one month."
        ),
    )
    deleted_on = models.DateTimeField(
        _("Deleted on"),
        null=True,
        blank=True,
        help_text=_("Date when the plugin was marked for deletion"),
    )

    # True if the plugin has a server interface
    server = models.BooleanField(
        _("Server"),
        default=False,
        db_index=True,
        help_text=_(
            "A server plugin is a plugin which can run on QGIS Server,"
            " by having a entrypoint <code>serverClassFactory</code>, see the"
            ' <a href="https://docs.qgis.org/latest/en/docs/pyqgis_developer_cookbook/server.html#init-py" target="_blank">documentation</a>.'
        ),
    )

    # Managers
    objects = models.Manager()
    base_objects = BasePluginManager()
    approved_objects = ApprovedPlugins()
    stable_objects = StablePlugins()
    experimental_objects = ExperimentalPlugins()
    new_qgis_ready_objects = NewQgisMajorVersionReadyPlugins()
    featured_objects = FeaturedPlugins()
    fresh_objects = FreshPlugins()
    latest_objects = LatestPlugins()
    unapproved_objects = UnapprovedPlugins()
    deprecated_objects = DeprecatedPlugins()
    popular_objects = PopularPlugins()
    most_downloaded_objects = MostDownloadedPlugins()
    most_voted_objects = MostVotedPlugins()
    best_rated_objects = BestRatedPlugins()
    server_objects = ServerPlugins()
    feedback_completed_objects = FeedbackCompletedPlugins()
    feedback_received_objects = FeedbackReceivedPlugins()
    feedback_pending_objects = FeedbackPendingPlugins()

    rating = AnonymousRatingField(
        range=5, use_cookies=True, can_change_vote=True, allow_delete=True
    )

    tags = TaggableManager(blank=True)

    @property
    def approved(self):
        """
        Returns True if the plugin has at least one approved version
        """
        return self.pluginversion_set.filter(approved=True).count() > 0

    @property
    def trusted(self):
        """
        Returns True if the plugin's author has plugins.can_approve permission
        Purpose of this decorator is to show/hide buttons in the template
        """
        return self.created_by.has_perm("plugins.can_approve")

    @property
    def stable(self):
        """
        Returns the latest stable and approved version
        """
        try:
            return self.pluginversion_set.filter(
                approved=True, experimental=False
            ).order_by("-version")[0]
        except:
            return None

    @property
    def experimental(self):
        """
        Returns the latest experimental and approved version
        """
        try:
            return self.pluginversion_set.filter(
                approved=True, experimental=True
            ).order_by("-version")[0]
        except:
            return None

    @property
    def latest_version(self):
        """
        Returns the most recent version regardless of approval or blocked
        status. Used to surface the security scan badge even when a plugin
        has no published stable/experimental version (e.g. blocked uploads).
        """
        return self.pluginversion_set.order_by("-version").first()

    @property
    def editors(self):
        """
        Returns a list of users that can edit the plugin: creator and owners
        """
        l = [o for o in self.owners.all()]
        l.append(self.created_by)
        return l

    @property
    def approvers(self):
        """
        Returns a list of editor users that can approve a version
        """
        return [l for l in self.editors if l.has_perm("plugins.can_approve")]

    @property
    def avg_vote(self):
        """
        Returns the rating_score/(rating_votes+0.001) value, this
        calculation is also available in manager's queries as
        "average_vote".
        This property is still useful when the object is not loaded
        through a manager, for example in related objects.
        """
        return self.rating_score / (self.rating_votes + 0.001)

    class Meta:
        ordering = ("name",)
        # ABP: Note: this permission should belong to the
        # PluginVersion class. I left it here because it
        # doesn't really matters where it is. Just be
        # sure you query for it using the 'plugins' class
        # instead of the 'pluginversion' class.
        permissions = (("can_approve", "Can approve plugins versions"),)

    def get_absolute_url(self):
        return reverse("plugin_detail", args=(self.package_name,))

    def __unicode__(self):
        return "[%s] %s" % (self.pk, self.name)

    def __str__(self):
        return self.__unicode__()

    def clean(self):
        """
        Validates:

        * Checks that package_name respect regexp [A-Za-z][A-Za-z0-9-_]+
        * checks for case-insensitive unique package_name
        """
        from django.core.exceptions import ValidationError

        if not re.match(r"^[A-Za-z][A-Za-z0-9-_]+$", self.package_name):
            raise ValidationError(
                _(
                    "Plugin package_name (which equals to the main plugin folder inside the zip file) must start with an ASCII letter and can contain only ASCII letters, digits and the - and _ signs."
                )
            )

        if self.pk:
            qs = Plugin.objects.filter(name__iexact=self.name).exclude(pk=self.pk)
        else:
            qs = Plugin.objects.filter(name__iexact=self.name)
        if qs.count():
            raise ValidationError(
                _(
                    "A plugin with a similar name (%s) already exists (the name only differs in case)."
                )
                % qs.all()[0].name
            )

        if self.pk:
            qs = Plugin.objects.filter(package_name__iexact=self.package_name).exclude(
                pk=self.pk
            )
        else:
            qs = Plugin.objects.filter(package_name__iexact=self.package_name)
        if qs.count():
            raise ValidationError(
                _(
                    "A plugin with a similar package_name (%s) already exists (the package_name only differs in case)."
                )
                % qs.all()[0].package_name
            )

    def to_json(
        self,
        authorized: bool = False,
        latest_version: "PluginVersion | None" = None,
        approved_versions: "models.QuerySet | list | None" = None,
    ) -> dict:
        """
        Returns a dict representation of the plugin for JSON serialization.
        Pass approved_versions as a queryset/list of PluginVersion objects.
        """
        return {
            "name": self.name,
            "package_name": self.package_name,
            "description": self.description,
            "about": self.about,
            "homepage": self.homepage,
            "repository": self.repository,
            "tracker": self.tracker,
            "author": self.author,
            "tags": [t.name for t in self.tags.all()],
            "downloads": self.downloads,
            "latest_version": str(latest_version.version) if latest_version else None,
            "versions": [
                v.to_json(authorized=authorized) for v in (approved_versions or [])
            ],
        }

    def save(self, keep_date=False, *args, **kwargs):
        """
        Soft triggers:
        * updates modified_on if keep_date is not set
        * set maintainer to the plugin creator when not specified
        * invalidates unconfirmed email confirmations when email changes
        """
        if self.pk and not keep_date:
            import logging

            logging.debug("Updating modified_on for the Plugin instance")
            self.modified_on = datetime.datetime.now()
        if not self.pk:
            self.modified_on = datetime.datetime.now()
        if not self.maintainer:
            self.maintainer = self.created_by
        if self.pk:
            try:
                old_email = Plugin.objects.values_list("email", flat=True).get(
                    pk=self.pk
                )
                if old_email != self.email:
                    # Remove this plugin from every *pending* confirmation that
                    # was sent to the old address.  Confirmed records are
                    # historical and must not be touched.  If the pending
                    # confirmation has no plugins left afterwards, delete it.
                    for conf in self.email_confirmations.filter(
                        email=old_email, confirmed_at__isnull=True
                    ):
                        conf.plugins.remove(self)
                        if not conf.plugins.exists():
                            conf.delete()
            except Plugin.DoesNotExist:
                pass
        super(Plugin, self).save(*args, **kwargs)


# Plugin version managers


class ApprovedPluginVersions(models.Manager):
    """
    Shows only public plugin versions.
    """

    def get_queryset(self):
        return (
            super(ApprovedPluginVersions, self)
            .get_queryset()
            .filter(approved=True)
            .order_by("-version")
        )


class StablePluginVersions(ApprovedPluginVersions):
    """
    Shows only approved public plugin versions: i.e. those with "approved" flag set
    and with "stable" flag
    """

    def get_queryset(self):
        return (
            super(StablePluginVersions, self).get_queryset().filter(experimental=False)
        )


class ExperimentalPluginVersions(ApprovedPluginVersions):
    """
    Shows only public plugin versions: i.e. those with "approved" flag set
    and with  "experimental" flag
    """

    def get_queryset(self):
        return (
            super(ExperimentalPluginVersions, self)
            .get_queryset()
            .filter(experimental=True)
        )


VALIDATION_STATUS_PENDING = "pending"
VALIDATION_STATUS_VALIDATING = "validating"
VALIDATION_STATUS_VALIDATED = "validated"
VALIDATION_STATUS_VALIDATED_WITH_CONFIG = "validated_with_config"
VALIDATION_STATUS_BLOCKED = "blocked"

VALIDATION_STATUS_CHOICES = [
    (VALIDATION_STATUS_PENDING, _("Pending")),
    (VALIDATION_STATUS_VALIDATING, _("Validating")),
    (VALIDATION_STATUS_VALIDATED, _("Validated")),
    (VALIDATION_STATUS_VALIDATED_WITH_CONFIG, _("Validated (configured)")),
    (VALIDATION_STATUS_BLOCKED, _("Blocked")),
]


def vjust(str, level=3, delim=".", bitsize=3, fillchar=" ", force_zero=False):
    """
    Normalize a dotted version string.

    1.12 becomes : 1.    12
    1.1  becomes : 1.     1


    if force_zero=True and level=2:

    1.12 becomes : 1.    12.     0
    1.1  becomes : 1.     1.     0


    """
    if not str:
        return str
    nb = str.count(delim)
    if nb < level:
        if force_zero:
            str += (level - nb) * (delim + "0")
        else:
            str += (level - nb) * delim
    parts = []
    for v in str.split(delim)[: level + 1]:
        if not v:
            parts.append(v.rjust(bitsize, "#"))
        else:
            parts.append(v.rjust(bitsize, fillchar))
    return delim.join(parts)


class VersionField(models.CharField):

    description = 'Field to store version strings ("a.b.c.d") in a way it is sortable'

    def get_prep_value(self, value):
        return vjust(value, fillchar="0")

    def to_python(self, value):
        if not value:
            return ""
        return re.sub(VERSION_RE, "", value)

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return self.to_python(value)


class QGVersionZeroForcedField(models.CharField):

    description = 'Field to store version strings ("a.b.c.d") in a way it \
    is sortable and QGIS scheme compatible (x.y.z).'

    def get_prep_value(self, value):
        return vjust(value, fillchar="0", level=2, force_zero=True)

    def to_python(self, value):
        if not value:
            return ""
        return re.sub(VERSION_RE, "", value)

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return self.to_python(value)


class PluginOutstandingToken(models.Model):
    """
    Plugin outstanding token
    """

    plugin = models.ForeignKey(Plugin, on_delete=models.CASCADE)
    token = models.ForeignKey(OutstandingToken, on_delete=models.CASCADE)
    is_blacklisted = models.BooleanField(default=False)
    is_newly_created = models.BooleanField(default=False)
    description = models.CharField(
        verbose_name=_("Description"),
        help_text=_(
            "Describe this token so that it's easier to remember where you're using it."
        ),
        max_length=512,
        blank=True,
        null=True,
    )
    last_used_on = models.DateTimeField(
        verbose_name=_("Last used on"), blank=True, null=True
    )


class PluginVersion(models.Model):
    """
    Plugin versions
    """

    # link to parent
    plugin = models.ForeignKey(Plugin, on_delete=models.CASCADE)
    # dates
    created_on = models.DateTimeField(
        _("Created on"), auto_now_add=True, editable=False
    )
    # download counter
    downloads = models.IntegerField(_("Downloads"), default=0, editable=False)
    # owners
    created_by = models.ForeignKey(
        User,
        verbose_name=_("Created by"),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    # version info, the first should be read from plugin
    min_qg_version = QGVersionZeroForcedField(
        _("Minimum QGIS version"), max_length=32, db_index=True
    )
    max_qg_version = QGVersionZeroForcedField(
        _("Maximum QGIS version"), max_length=32, null=True, blank=True, db_index=True
    )
    version = VersionField(_("Version"), max_length=32, db_index=True)
    changelog = models.TextField(_("Changelog"), null=True, blank=True)

    # the file!
    package = models.FileField(_("Plugin package"), upload_to=PLUGINS_STORAGE_PATH)
    # Flags: checks on unique current/experimental are done in save() and possibly in the views
    experimental = models.BooleanField(
        _("Experimental flag"),
        default=False,
        help_text=_(
            "Check this box if this version is experimental, leave unchecked if it's stable. Please note that this field might be overridden by metadata (if present)."
        ),
        db_index=True,
    )
    approved = models.BooleanField(
        _("Approved"),
        default=True,
        help_text=_("Set to false if you wish to unapprove the plugin version."),
        db_index=True,
    )
    external_deps = models.CharField(
        _("External dependencies"),
        help_text=_("PIP install string"),
        max_length=512,
        blank=False,
        null=True,
    )
    is_from_token = models.BooleanField(_("Is uploaded using token"), default=False)

    # Validation status for security and QA checks
    validation_status = models.CharField(
        _("Validation status"),
        max_length=25,
        choices=VALIDATION_STATUS_CHOICES,
        default=VALIDATION_STATUS_PENDING,
        db_index=True,
        help_text=_(
            "Validation status based on security and quality checks. "
            "New uploads start as 'validating' until checks complete. "
            "'blocked' means critical issues were found and the version "
            "is not available for approval or download."
        ),
    )

    # Link to the token if upload is using token
    token = models.ForeignKey(
        PluginOutstandingToken,
        verbose_name=_("Token used"),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    # Managers, used in xml output
    objects = models.Manager()
    approved_objects = ApprovedPluginVersions()
    stable_objects = StablePluginVersions()
    experimental_objects = ExperimentalPluginVersions()

    # Check qt6
    class Qt6Status(models.TextChoices):
        NOT_RUN = "not_run", _("Not run")
        PENDING = "pending", _("Pending")
        COMPATIBLE = "compatible", _("Compatible")
        NOT_COMPATIBLE = "not_compatible", _("Not compatible")

    qt6_status = models.CharField(
        _("Qt6 status"),
        max_length=20,
        choices=Qt6Status.choices,
        default=Qt6Status.NOT_RUN,
        db_index=True,
    )
    qt6_logs = models.TextField(blank=True)
    qt6_checked_on = models.DateTimeField(null=True, blank=True)


    @property
    def is_available(self):
        """
        Returns True if the version is available for download/approval
        (not blocked by security checks).
        """
        return self.validation_status not in [
            VALIDATION_STATUS_PENDING,
            VALIDATION_STATUS_VALIDATING,
            VALIDATION_STATUS_BLOCKED,
        ]

    @property
    def file_name(self):
        return os.path.basename(self.package.file.name)

    def save(self, *args, **kwargs):
        """
        Soft triggers:
        * updates modified_on in parent
        """
        # Transforms the version...
        # Need to be done here too, because clean()
        # is only called in forms.
        if self.version.rfind(" ") > 0:
            self.version = self.version.rsplit(" ")[-1]

        # Only change modified_on when a new version is created,
        # every download triggers a save to update the counter
        if not self.pk:
            self.plugin.modified_on = self.created_on
            self.plugin.save()

        # fix Max version
        if not self.max_qg_version:
            self.max_qg_version = "%s.99" % tuple(self.min_qg_version.split(".")[0])

        super(PluginVersion, self).save(*args, **kwargs)

    def clean(self):
        """
        Validates:

        * checks for unique
        * checks for version only digits and dots
        """
        from django.core.exceptions import ValidationError

        # Transforms the version
        self.version = PluginVersion.clean_version(self.version)

        versions_to_check = PluginVersion.objects.filter(
            plugin=self.plugin, version=self.version
        )
        if self.pk:
            versions_to_check = versions_to_check.exclude(pk=self.pk)
        # Checks for unique_together
        if (
            versions_to_check.filter(plugin=self.plugin, version=self.version).count()
            > 0
        ):
            raise ValidationError(
                _(
                    "Version value must be unique among each plugin: a version with same number already exists."
                )
            )

    @staticmethod
    def clean_version(version):
        """
        Strips blanks and Version string
        """
        if version.rfind(" ") > 0:
            version = version.rsplit(" ")[-1]
        return version

    class Meta:
        unique_together = ("plugin", "version")
        ordering = ("plugin", "-version", "experimental")

    def get_absolute_url(self):
        return reverse(
            "version_detail",
            args=(
                self.plugin.package_name,
                self.version,
            ),
        )

    def get_download_url(self):
        return reverse(
            "version_download",
            args=(
                self.plugin.package_name,
                self.version,
            ),
        )

    def download_file_name(self):
        return "%s.%s.zip" % (self.plugin.package_name, self.version)

    def __unicode__(self):
        desc = "%s %s" % (self.plugin, self.version)
        if self.experimental:
            desc = "%s %s" % (desc, _("Experimental"))
        return desc

    def __str__(self):
        return self.__unicode__()

    def to_json(
        self,
        authorized: bool = False,
        include_detail: bool = False,
        download_url: str | None = None,
    ) -> dict:
        """
        Returns a dict representation of this version for JSON serialization.

        authorized     -- include validation_status and security scan info.
        include_detail -- include changelog, external_deps, download_url, and
                          the full security scan report (files_scanned,
                          total_issues, scan_report).
        download_url   -- absolute download URL string (only used when
                          include_detail=True).
        """
        data = {
            "version": str(self.version),
            "experimental": self.experimental,
            "qgis_min": str(self.min_qg_version),
            "qgis_max": str(self.max_qg_version),
            "downloads": self.downloads,
            "uploaded_by": self.created_by.username if self.created_by else None,
            "upload_datetime": self.created_on.isoformat(),
        }
        if include_detail:
            data["changelog"] = self.changelog
            data["external_deps"] = self.external_deps
            if download_url is not None:
                data["download_url"] = download_url
        if authorized:
            data["validation_status"] = self.validation_status
            try:
                data["security_scan"] = self.security_scan.to_json(full=include_detail)
            except PluginVersionSecurityScan.DoesNotExist:
                data["security_scan"] = None
        return data


class PluginVersionFeedback(models.Model):
    """Feedback for a plugin version."""

    version = models.ForeignKey(
        PluginVersion, on_delete=models.CASCADE, related_name="feedback"
    )
    reviewer = models.ForeignKey(
        User,
        verbose_name=_("Reviewed by"),
        help_text=_("The user who reviewed this plugin."),
        on_delete=models.CASCADE,
    )
    task = models.TextField(
        verbose_name=_("Task"),
        help_text=_(
            "A feedback task. Please write your review as a task for this plugin."
        ),
        max_length=1000,
        blank=False,
        null=False,
    )
    created_on = models.DateTimeField(
        verbose_name=_("Created on"), auto_now_add=True, editable=False
    )
    modified_on = models.DateTimeField(
        _("Modified on"), editable=False, blank=True, null=True
    )

    completed_on = models.DateTimeField(
        verbose_name=_("Completed on"), blank=True, null=True
    )
    is_completed = models.BooleanField(
        verbose_name=_("Completed"), default=False, db_index=True
    )

    class Meta:
        verbose_name = _("Plugin Version Feedback")
        verbose_name_plural = _("Plugin Version Feedbacks")

    def save(self, *args, **kwargs):
        if self.is_completed is True:
            self.completed_on = timezone.now()
        else:
            self.completed_on = None
        super(PluginVersionFeedback, self).save(*args, **kwargs)


class PluginVersionFeedbackAttachment(models.Model):
    """Image attachments for feedback."""

    feedback = models.ForeignKey(
        PluginVersionFeedback, on_delete=models.CASCADE, related_name="attachments"
    )
    image = models.ImageField(
        verbose_name=_("Image"),
        upload_to=PLUGINS_STORAGE_PATH,
        help_text=_("Upload screenshots or images to support your feedback"),
    )
    caption = models.CharField(
        verbose_name=_("Caption"),
        max_length=255,
        blank=True,
        null=True,
        help_text=_("Optional caption for the image"),
    )
    created_on = models.DateTimeField(
        verbose_name=_("Created on"), auto_now_add=True, editable=False
    )

    class Meta:
        verbose_name = _("Feedback Attachment")
        verbose_name_plural = _("Feedback Attachments")

    def __str__(self):
        return f"Attachment for {self.feedback}"


def delete_version_package(sender, instance, **kw):
    """
    Removes the zip package
    """
    try:
        os.remove(instance.package.path)
    except:
        pass


def delete_plugin_icon(sender, instance, **kw):
    """
    Removes the plugin icon
    """
    try:
        instance.icon.delete(False)
    except:
        pass


def delete_feedback_attachment(sender, instance, **kw):
    """
    Removes the feedback attachment image
    """
    try:
        instance.image.delete(False)
    except:
        pass


class PluginVersionDownload(models.Model):
    """
    Plugin version downloads
    """

    plugin_version = models.ForeignKey(PluginVersion, on_delete=models.CASCADE)
    download_date = models.DateField(default=timezone.now)
    country_code = models.CharField(max_length=3, default="N/D")
    country_name = models.CharField(max_length=100, default="N/D")
    download_count = models.IntegerField(default=0)

    class Meta:
        unique_together = (
            "plugin_version",
            "download_date",
            "country_code",
            "country_name",
        )


class SecurityRule(models.Model):
    """
    Configurable security and quality check rules.
    Administrators can enable/disable specific rules and mark them as skippable.
    """

    CATEGORY_CHOICES = [
        ("bandit", _("Bandit Security")),
        ("secrets", _("Detect Secrets")),
        ("flake8", _("Flake8 Quality")),
        ("file_analysis", _("File Analysis")),
    ]

    SEVERITY_CHOICES = [
        ("info", _("Info")),
        ("warning", _("Warning")),
        ("critical", _("Critical")),
    ]

    check_category = models.CharField(
        _("Category"),
        max_length=50,
        choices=CATEGORY_CHOICES,
        db_index=True,
        help_text=_("Security/quality tool category"),
    )
    check_code = models.CharField(
        _("Code"),
        max_length=50,
        unique=True,
        db_index=True,
        help_text=_("Unique check identifier (e.g., B101, E501)"),
    )
    check_name = models.CharField(
        _("Name"),
        max_length=200,
        help_text=_("Human-readable check name"),
    )
    check_description = models.TextField(
        _("Description"),
        help_text=_("Detailed description of what this check does"),
    )
    severity = models.CharField(
        _("Severity"),
        max_length=20,
        choices=SEVERITY_CHOICES,
        default="info",
        help_text=_("Severity level of issues found by this check"),
    )
    enabled = models.BooleanField(
        _("Enabled"),
        default=False,
        db_index=True,
        help_text=_("Whether this check is active (disabled by default)"),
    )
    can_be_skipped = models.BooleanField(
        _("Can be skipped"),
        default=True,
        help_text=_("Whether plugin developers can skip this check during upload"),
    )
    created_on = models.DateTimeField(
        _("Created on"), default=timezone.now, editable=False
    )
    updated_on = models.DateTimeField(_("Updated on"), auto_now=True)

    class Meta:
        verbose_name = _("Security Rule")
        verbose_name_plural = _("Security Rules")
        ordering = ["check_category", "check_code"]
        indexes = [
            models.Index(fields=["check_category", "enabled"]),
            models.Index(fields=["enabled", "can_be_skipped"]),
        ]

    def __str__(self):
        return f"{self.check_code}: {self.check_name}"


class PluginVersionSecurityScan(models.Model):
    """
    Security and quality scan results for plugin versions
    Stores non-blocking security, quality, and code analysis results
    """

    plugin_version = models.OneToOneField(
        PluginVersion, on_delete=models.CASCADE, related_name="security_scan"
    )
    scanned_on = models.DateTimeField(
        _("Scanned on"), default=timezone.now, editable=False
    )

    # Summary statistics
    total_checks = models.IntegerField(_("Total checks"), default=0)
    passed_checks = models.IntegerField(_("Passed checks"), default=0)
    warning_count = models.IntegerField(_("Warnings"), default=0)
    critical_count = models.IntegerField(_("Critical issues"), default=0)
    info_count = models.IntegerField(_("Info items"), default=0)
    files_scanned = models.IntegerField(_("Files scanned"), default=0)
    total_issues = models.IntegerField(_("Total issues"), default=0)

    # Rule tracking
    enabled_rules_count = models.IntegerField(
        _("Enabled rules count"),
        default=0,
        help_text=_("Number of rules that were enabled when this scan ran"),
    )
    skipped_rules = models.JSONField(
        _("Skipped rules"),
        default=list,
        blank=True,
        help_text=_("List of rule codes that were skipped by the developer"),
    )
    config_files_detected = models.JSONField(
        _("Config files detected"),
        default=list,
        blank=True,
        help_text=_(
            "Config files found in the plugin ZIP that may have influenced scan results "
            "(e.g. .bandit, .secrets.baseline, .flake8)"
        ),
    )

    # Full scan report (JSON field)
    scan_report = models.JSONField(
        _("Scan report"),
        default=dict,
        blank=True,
        help_text=_("Complete scan report with all check details"),
    )

    class Meta:
        verbose_name = _("Plugin Version Security Scan")
        verbose_name_plural = _("Plugin Version Security Scans")
        ordering = ["-scanned_on"]

    def __str__(self):
        return f"Security scan for {self.plugin_version} ({self.scanned_on})"

    @property
    def overall_status(self):
        """Returns overall scan status"""
        if self.critical_count > 0:
            return "critical"
        elif self.warning_count > 0:
            return "warning"
        elif self.info_count > 0:
            return "info"
        else:
            return "passed"

    @property
    def pass_rate(self):
        """Calculate percentage of passed checks"""
        if self.total_checks == 0:
            return 0
        return round((self.passed_checks / self.total_checks) * 100, 1)

    def to_json(self, full: bool = False) -> dict:
        """
        Returns a dict representation of this scan for JSON serialization.
        full=True includes files_scanned, total_issues, and scan_report.
        """
        data = {
            "status": self.overall_status,
            "pass_rate": self.pass_rate,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "warning_count": self.warning_count,
            "critical_count": self.critical_count,
            "info_count": self.info_count,
            "scanned_on": self.scanned_on.isoformat(),
        }
        if full:
            data["files_scanned"] = self.files_scanned
            data["total_issues"] = self.total_issues
            data["scan_report"] = self.scan_report
        return data


class PluginVersionSecurityRuleSkip(models.Model):
    """
    Tracks which security rules were skipped by developers during upload.
    Allows auditing of developer decisions and understanding why scans were bypassed.
    """

    plugin_version = models.ForeignKey(
        PluginVersion,
        on_delete=models.CASCADE,
        related_name="skipped_security_rules",
    )
    security_rule = models.ForeignKey(
        SecurityRule,
        on_delete=models.CASCADE,
        related_name="skipped_by_versions",
    )
    skipped_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="skipped_security_rules",
    )
    skipped_on = models.DateTimeField(
        _("Skipped on"), default=timezone.now, editable=False
    )
    reason = models.TextField(
        _("Reason"),
        blank=True,
        help_text=_("Optional reason for skipping this rule"),
    )

    class Meta:
        verbose_name = _("Plugin Version Security Rule Skip")
        verbose_name_plural = _("Plugin Version Security Rule Skips")
        ordering = ["-skipped_on"]
        unique_together = [("plugin_version", "security_rule")]

    def __str__(self):
        return f"{self.plugin_version} skipped {self.security_rule.check_code}"


models.signals.post_delete.connect(delete_version_package, sender=PluginVersion)
models.signals.post_delete.connect(delete_plugin_icon, sender=Plugin)
models.signals.post_delete.connect(
    delete_feedback_attachment, sender=PluginVersionFeedbackAttachment
)


PLUGIN_EMAIL_CONFIRMATION_EXPIRY_DAYS = getattr(
    settings, "PLUGIN_EMAIL_CONFIRMATION_EXPIRY_DAYS", 30
)


class PluginEmailConfirmation(models.Model):
    """
    One record per email address per confirmation round.

    ``plugins`` (M2M) lists every plugin whose author email matches this
    address at the time the confirmation was sent.  When a plugin's email
    changes, it is removed from the M2M; if no plugins remain, the record
    is deleted.

    A single ``key`` is the confirmation token — clicking the link in the
    email confirms the address for all plugins in the M2M at once.
    """

    email = models.EmailField(
        _("Email address"),
        db_index=True,
        help_text=_("The address being confirmed."),
    )
    plugins = models.ManyToManyField(
        Plugin,
        related_name="email_confirmations",
        verbose_name=_("Plugins"),
    )
    key = models.CharField(
        _("Confirmation key"),
        max_length=64,
        unique=True,
        editable=False,
    )
    sent_at = models.DateTimeField(_("Sent at"), auto_now_add=True)
    confirmed_at = models.DateTimeField(_("Confirmed at"), null=True, blank=True)
    expires_at = models.DateTimeField(_("Expires at"))

    class Meta:
        verbose_name = _("Plugin Email Confirmation")
        verbose_name_plural = _("Plugin Email Confirmations")
        ordering = ["-sent_at"]

    def __str__(self):
        status = (
            "confirmed"
            if self.is_confirmed
            else ("expired" if self.is_expired else "pending")
        )
        count = self.plugins.count()
        return f"<{self.email}> [{count} plugin(s)] [{status}]"

    @property
    def is_confirmed(self):
        return self.confirmed_at is not None

    @property
    def is_expired(self):
        return not self.is_confirmed and timezone.now() > self.expires_at

    def confirm(self):
        """Mark this confirmation as done."""
        self.confirmed_at = timezone.now()
        self.save(update_fields=["confirmed_at"])

    @classmethod
    def create_for_email(cls, email, plugins):
        """
        Create (or reuse) a pending confirmation for *email* covering *plugins*.

        Only plugins whose current ``email`` field still matches are included.
        Returns ``(confirmation, created)``.  If no valid plugins remain,
        returns ``(None, False)``.  If all valid plugins are already confirmed
        for this address, also returns ``(None, False)``.
        """
        now = timezone.now()
        expiry = now + datetime.timedelta(days=PLUGIN_EMAIL_CONFIRMATION_EXPIRY_DAYS)

        # Only include plugins whose email still matches what we're confirming.
        valid_plugins = [p for p in plugins if p.email == email]
        if not valid_plugins:
            return None, False

        # If every valid plugin already has a confirmed record for this email, skip.
        all_confirmed = all(
            cls.objects.filter(
                email=email,
                confirmed_at__isnull=False,
                plugins=plugin,
            ).exists()
            for plugin in valid_plugins
        )
        if all_confirmed:
            return None, False

        # Reuse an existing unexpired pending confirmation for this email.
        existing = cls.objects.filter(
            email=email,
            confirmed_at__isnull=True,
            expires_at__gt=now,
        ).first()
        if existing:
            existing.plugins.set(valid_plugins)
            return existing, False

        # Create a fresh confirmation.
        confirmation = cls.objects.create(
            email=email,
            key=secrets.token_urlsafe(48),
            expires_at=expiry,
        )
        confirmation.plugins.set(valid_plugins)
        return confirmation, True


class PluginEmailConfirmationError(models.Model):
    """
    Records a failed attempt to send a confirmation email.

    Written by both the management command and the admin action so that
    errors are queryable and visible in the Django admin without needing
    to inspect log files or command output.
    """

    email = models.EmailField(_("Email address"), db_index=True)
    plugins = models.TextField(
        _("Plugins"),
        help_text=_("Comma-separated list of plugin package names."),
    )
    error = models.TextField(_("Error message"))
    occurred_at = models.DateTimeField(_("Occurred at"), auto_now_add=True)

    class Meta:
        verbose_name = _("Plugin Email Confirmation Error")
        verbose_name_plural = _("Plugin Email Confirmation Errors")
        ordering = ["-occurred_at"]

    def __str__(self):
        return f"<{self.email}> — {self.occurred_at}"


class PluginEmailCommunication(models.Model):
    """
    A one-off news/announcement broadcast composed by a superuser and sent
    (BCC, asynchronously) to every confirmed plugin contact address plus the
    account emails of those plugins' collaborators.

    Stored for audit (what was sent, when, to how many) and used as the
    payload for the Celery send task.
    """

    STATUS_QUEUED = "queued"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_QUEUED, _("Queued")),
        (STATUS_SENT, _("Sent")),
        (STATUS_FAILED, _("Failed")),
    ]

    subject = models.CharField(_("Subject"), max_length=255)
    body = models.TextField(_("Message"))
    created_by = models.ForeignKey(
        User,
        verbose_name=_("Created by"),
        related_name="email_communications",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("Created at"), auto_now_add=True)
    sent_at = models.DateTimeField(_("Sent at"), null=True, blank=True)
    recipient_count = models.PositiveIntegerField(_("Recipient count"), default=0)
    status = models.CharField(
        _("Status"),
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_QUEUED,
    )
    error = models.TextField(_("Error message"), blank=True, default="")

    class Meta:
        verbose_name = _("Plugin Email Communication")
        verbose_name_plural = _("Plugin Email Communications")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subject} [{self.status}] ({self.recipient_count} recipients)"
