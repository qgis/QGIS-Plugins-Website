# Custom haystack search to match partial strings

from django.urls import re_path as url
from haystack.query import SQ, SearchQuerySet
from haystack.views import SearchView


class SearchWithRequest(SearchView):

    __qualname__ = "SearchWithRequest"

    def build_form(self, form_kwargs=None):
        if form_kwargs is None:
            form_kwargs = {}

        if self.searchqueryset is None:
            q = self.request.GET.get("q", "")
            sqs = SearchQuerySet().filter(
                SQ(name_auto=q)
                | SQ(text=q)
                | SQ(package_name_auto=q)
                | SQ(author_auto=q)
                | SQ(created_by_auto=q)
            )
            form_kwargs["searchqueryset"] = sqs

        return super(SearchWithRequest, self).build_form(form_kwargs)

    def get_results(self):
        return self.form.searchqueryset.order_by("-downloads")


urlpatterns = [
    url(r"^$", SearchWithRequest(load_all=False), {}, name="haystack_search"),
]
