# Custom haystack search to match partial strings

from django.urls import re_path as url
from haystack.query import SearchQuerySet
from haystack.views import SearchView


class SearchWithRequest(SearchView):

    __qualname__ = "SearchWithRequest"

    def build_form(self, form_kwargs=None):
        if form_kwargs is None:
            form_kwargs = {}

        if self.searchqueryset is None:
            sqs1 = SearchQuerySet().filter(
                description_auto=self.request.GET.get("q", "")
            )
            sqs2 = SearchQuerySet().filter(
                about_auto=self.request.GET.get("q", "")
            )
            sqs3 = SearchQuerySet().filter(name_auto=self.request.GET.get("q", ""))
            sqs4 = SearchQuerySet().filter(text=self.request.GET.get("q", ""))
            sqs5 = SearchQuerySet().filter(
                package_name_auto=self.request.GET.get("q", "")
            )
            form_kwargs["searchqueryset"] = sqs1 | sqs2 | sqs3 | sqs4 | sqs5

        return super(SearchWithRequest, self).build_form(form_kwargs)

    def get_results(self):
        """
        Fetches the search results and sorts them in descending order based on the 'downloads' attribute.
        If the 'downloads' attribute is not present or the object is None, it defaults to 0.
        """
        results = self.form.searchqueryset
        sort_by = 'downloads'
        results = sorted(
            results, 
            key=lambda x: int(
                getattr(x.object, sort_by)
            ) if x.object is not None else 0,
            reverse=True  # Reverse the sort order
        )
        return results


urlpatterns = [
    url(r"^$", SearchWithRequest(load_all=False), {}, name="haystack_search"),
]
