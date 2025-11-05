import ast
import os

from celery.schedules import crontab
from settings import *

SITE_ROOT = os.path.dirname(os.path.realpath(__file__))
from datetime import timedelta

from django.contrib.staticfiles.storage import ManifestStaticFilesStorage

DEBUG = ast.literal_eval(os.environ.get("DEBUG", "True"))
THUMBNAIL_DEBUG = DEBUG
ALLOWED_HOSTS = ["*"]

# Absolute filesystem path to the directory that will hold user-uploaded files.
# Example: "/var/www/example.com/media/"
MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/home/web/media/")

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash.
# Examples: "http://example.com/media/", "http://media.example.com/"
# MEDIA_URL = '/media/'
# setting full MEDIA_URL to be able to use it for the feeds
MEDIA_URL = "/media/"

# Absolute path to the directory static files should be collected to.
# Don't put anything in this directory yourself; store your static files
# in apps' "static/" subdirectories and in STATICFILES_DIRS.
# Example: "/var/www/example.com/static/"
STATIC_ROOT = os.environ.get("STATIC_ROOT", "/home/web/static/")

# URL prefix for static files.
# Example: "http://example.com/static/", "http://static.example.com/"
STATIC_URL = "/static/"

# Manage static files storage ensuring that their
# filenames contain a hash of their content for cache busting
# STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    # Uncomment the next line to enable the admin:
    "django.contrib.admin",
    # Uncomment the next line to enable admin documentation:
    # 'django.contrib.admindocs',
    "django.contrib.staticfiles",
    "django.contrib.flatpages",
    # full text search postgres
    "django.contrib.postgres",
    # ABP:
    "plugins",
    "django.contrib.humanize",
    "django.contrib.syndication",
    "bootstrap_pagination",
    "sortable_listview",
    "lib",  # Container for small tags and functions
    "sorl.thumbnail",
    "djangoratings",
    "taggit",
    "taggit_autosuggest",
    "taggit_templatetags",
    "haystack",
    "simplemenu",
    "tinymce",
    "rpc4django",
    "preferences",
    "rest_framework",
    "rest_framework.authtoken",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "sorl_thumbnail_serializer",  # serialize image
    "drf_multiple_model",
    "drf_yasg",
    "matomo",
    # Webpack
    "webpack_loader",
]

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": os.environ["DATABASE_NAME"],
        "USER": os.environ["DATABASE_USERNAME"],
        "PASSWORD": os.environ["DATABASE_PASSWORD"],
        "HOST": os.environ["DATABASE_HOST"],
        "PORT": 5432,
        "TEST": {
            "NAME": "unittests",
        },
    }
}

PAGINATION_DEFAULT_PAGINATION = 20
PAGINATION_DEFAULT_PAGINATION_HUB = 30
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
SERVE_STATIC_MEDIA = DEBUG
DEFAULT_PLUGINS_SITE = os.environ.get(
    "DEFAULT_PLUGINS_SITE", "https://plugins.qgis.org/"
)

# See fig.yml file for postfix container definition
#
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"
)
# Host for sending e-mail.
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp")
# Port for sending e-mail.
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "25"))
# SMTP authentication information for EMAIL_HOST.
# See fig.yml for where these are defined
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "automation")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "docker")
EMAIL_USE_TLS = ast.literal_eval(os.environ.get("EMAIL_USE_TLS", "False"))
EMAIL_SUBJECT_PREFIX = os.environ.get("EMAIL_SUBJECT_PREFIX", "[QGIS Plugins]")

# django uploaded file permission
FILE_UPLOAD_PERMISSIONS = 0o644

REST_FRAMEWORK = {
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

GEOIP_PATH = "/var/opt/maxmind/"
METABASE_DOWNLOAD_STATS_URL = os.environ.get("METABASE_DOWNLOAD_STATS_URL", "/metabase")
CELERY_RESULT_BACKEND = "rpc://"
CELERY_BROKER_URL = os.environ.get("BROKER_URL", "amqp://rabbitmq:5672")
CELERY_BEAT_SCHEDULE = {
    "generate_plugins_xml": {
        "task": "plugins.tasks.generate_plugins_xml.generate_plugins_xml",
        "schedule": crontab(minute="*/10"),  # Execute every 10 minutes.
        "kwargs": {"site": DEFAULT_PLUGINS_SITE},
    },
    "update_qgis_versions": {
        "task": "plugins.tasks.update_qgis_versions.update_qgis_versions",
        "schedule": crontab(minute="*/30"),  # Execute every 30 minutes.
    },
    # Index synchronization sometimes fails when deleting
    # a plugin and None is listed in the search list. So I think
    # it would be better if we rebuild the index frequently
    "rebuild_search_index": {
        "task": "plugins.tasks.rebuild_search_index.rebuild_search_index",
        "schedule": crontab(minute=0, hour=3),  # Execute every day at 3 AM.
    },
    "get_sustaining_members": {
        "task": "plugins.tasks.get_sustaining_members.get_sustaining_members",
        "schedule": crontab(minute="*/30"),  # Execute every 30 minutes.
    },
}
# Set plugin token access and refresh validity to a very long duration
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=365 * 1000),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=365 * 1000),
}

MATOMO_SITE_ID = "1"
MATOMO_URL = "//matomo.qgis.org/"

# Default primary key type
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"


# Set the maximum PLUGIN_MAX_UPLOAD_SIZE size to 25MB
# When changing this, make sure to also change the
# corresponding value in the "client_max_body_size" in
# the prod-ssl.conf and staging-ssl.conf
# files.
PLUGIN_MAX_UPLOAD_SIZE = os.environ.get(
    "PLUGIN_MAX_UPLOAD_SIZE", 25000000
)  # Default is 25MB

# RPC2 Max upload size
DATA_UPLOAD_MAX_MEMORY_SIZE = PLUGIN_MAX_UPLOAD_SIZE  # same as max allowed plugin size

# Plugin Notification Recipients Group Name
# used to send notifications when a new plugin
# or a new version is uploaded. This group usually
# contains the plugin approvers
# but can be customized.
NOTIFICATION_RECIPIENTS_GROUP_NAME = os.environ.get(
    "NOTIFICATION_RECIPIENTS_GROUP_NAME", "Plugin Notification Recipients"
)

# Sentry
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
SENTRY_RATE = os.environ.get("SENTRY_RATE", 1.0)

if SENTRY_DSN and SENTRY_DSN != "":
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        traces_sample_rate=SENTRY_RATE,
    )

# Webpack
WEBPACK_LOADER = {
    "DEFAULT": {
        "BUNDLE_DIR_NAME": "bundles",
        "STATS_FILE": os.path.join(SITE_ROOT, "webpack-stats.json"),
    }
}

CURRENT_QGIS_MAJOR_VERSION = os.environ.get("CURRENT_QGIS_MAJOR_VERSION", "3")
NEW_QGIS_MAJOR_VERSION = os.environ.get("NEW_QGIS_MAJOR_VERSION", "4")

# News and Updated menus
NEWS_MENU = [
    {
        "name": f"QGIS {NEW_QGIS_MAJOR_VERSION} Ready",
        "url": "/plugins/new_qgis_ready/",
        "order": 0,
        "is_highlighted": True,
    },
    {
        "name": "New Plugins",
        "url": "/plugins/fresh/",
        "order": 1,
    },
    {
        "name": "Updated Plugins",
        "url": "/plugins/latest/",
        "order": 2,
    },
]

# Featured, popular, most downloaded, most voted, best rated
TOP_MENU = [
    # Hidden for now, as we didn't set rules for featured plugins
    # Uncomment the following lines when ready to use featured plugins
    # {
    #     'name': 'Featured',
    #     'url': '/plugins/featured/',
    #     'order': 0,
    # },
    {
        "name": "Popular",
        "url": "/plugins/popular/",
        "order": 1,
    },
    {
        "name": "Most Downloaded",
        "url": "/plugins/most_downloaded/",
        "order": 2,
    },
    {
        "name": "Most Voted",
        "url": "/plugins/most_voted/",
        "order": 3,
    },
    {
        "name": "Best Rated Plugins",
        "url": "/plugins/best_rated/",
        "order": 4,
    },
]

# Review Resolved, Review Pending, Awaiting Review
REVIEW_MENU = [
    {
        "name": "Review Resolved",
        "url": "/plugins/feedback_completed/",
        "order": 0,
    },
    {
        "name": "Review Pending",
        "url": "/plugins/feedback_received/",
        "order": 1,
    },
    {
        "name": "Awaiting Review",
        "url": "/plugins/feedback_pending/",
        "order": 2,
    },
]

# Stable, experimental, server, deprecated
OTHER_MENU = [
    {
        "name": "Stable",
        "url": "/plugins/stable/",
        "order": 0,
    },
    {
        "name": "Experimental",
        "url": "/plugins/experimental/",
        "order": 1,
    },
    {
        "name": "Server",
        "url": "/plugins/server/",
        "order": 2,
    },
    {
        "name": "Deprecated",
        "url": "/plugins/deprecated/",
        "order": 3,
    },
]

# News menus, Top menus, Other menus
PLUGINS_CATEGORIES = [
    {
        "name": "News and Updated",
        "url": "#",
        "icon": "fa-newspaper",
        "order": 0,
        "submenu": NEWS_MENU,
    },
    {"name": "Top", "url": "#", "icon": "fa-star", "order": 1, "submenu": TOP_MENU},
    {
        "name": "Other Categories",
        "url": "#",
        "icon": "fa-ellipsis-h",
        "order": 3,
        "submenu": OTHER_MENU,
    },
]

NAVIGATION_MENU = [
    {
        "name": "Home",
        "url": "/",
        "icon": "fa-house",
        "order": 0,
    },
    {
        "name": "All Plugins",
        "url": "/plugins/",
        "icon": "fa-plug",
        "order": 1,
    },
    {
        "name": "My Plugins",
        "url": "/plugins/my",
        "icon": "fa-user",
        "order": 2,
        "requires_login": True,
    },
    {
        "name": "Review",
        "url": "#",
        "icon": "fa-check",
        "order": 3,
        "submenu": REVIEW_MENU,
        "requires_staff": True,
    },
    {
        "name": "Categories",
        "url": "#",
        "icon": "fa-list",
        "order": 4,
        "submenu": PLUGINS_CATEGORIES,
    },
    {
        "name": "Metrics",
        "url": "https://plugins-analytics.qgis.org",
        "icon": "fa-chart-bar",
        "order": 5,
    },
    {
        "name": "Admin",
        "url": "/admin/",
        "icon": "fa-tools",
        "order": 6,
        "requires_staff": True,
    },
]

# Local settings overrides
# Must be the last!
DJANGO_LOCAL_SETTINGS = os.environ.get("DJANGO_LOCAL_SETTINGS", "settings_local.py")

try:
    from pathlib import Path

    local_settings_path = Path(__file__).parent / DJANGO_LOCAL_SETTINGS
    if local_settings_path.exists():
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "settings_local", local_settings_path
        )
        settings_local = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(settings_local)
        for setting in dir(settings_local):
            if setting.isupper():
                globals()[setting] = getattr(settings_local, setting)
    else:
        raise ImportError(
            f"Local settings file {DJANGO_LOCAL_SETTINGS} does not exist."
        )
except ImportError:
    pass
