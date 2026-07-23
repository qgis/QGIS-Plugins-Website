from haystack import indexes
from plugins.models import Plugin


class PluginIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=True)
    created_by = indexes.CharField(model_attr="created_by")
    created_on = indexes.DateTimeField(model_attr="created_on")
    downloads = indexes.IntegerField(model_attr="downloads", default=0)
    # We add this for autocomplete.
    name_auto = indexes.EdgeNgramField(model_attr="name")
    package_name_auto = indexes.EdgeNgramField(model_attr="package_name", default="")
    author_auto = indexes.EdgeNgramField(model_attr="author", default="")
    created_by_auto = indexes.EdgeNgramField()

    def prepare_created_by_auto(self, obj):
        parts = [
            obj.created_by.username,
            obj.created_by.first_name,
            obj.created_by.last_name,
        ]
        return " ".join(filter(None, parts))

    def get_model(self):
        return Plugin

    def index_queryset(self, using=None):
        """Search in approved plugins, including those marked for deletion."""
        return Plugin.approved_objects.select_related("created_by").prefetch_related(
            "tags"
        )
