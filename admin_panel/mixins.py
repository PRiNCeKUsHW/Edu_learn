"""Shared plumbing for the admin_panel class-based views.

These mixins exist purely to remove the boilerplate that used to be
copy-pasted across every Subject/ClassLevel/Chapter/Lesson/Quiz/... CRUD
view in views.py — the staff gate, the sidebar `page` flag, the pager
querystring, and the form/confirm-delete template context. None of them
change what staff see or how the panel behaves; every existing template
(`admin_panel/form.html`, `admin_panel/confirm_delete.html`,
`admin_panel/_pager.html`) is driven off exactly the same context keys it
always was.
"""
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.urls import reverse
from django.utils.decorators import method_decorator


class StaffRequiredMixin:
    """Class-based equivalent of the old `@staff_member_required` decorator.

    Applied via `dispatch` so it behaves identically to decorating a
    function view: same login_url ('admin:login', staff_member_required's
    own default), same redirect_field_name, same is_active/is_staff test.
    """

    page = None  # sidebar section key the templates highlight, e.g. 'subjects'

    @method_decorator(staff_member_required)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page'] = self.page
        return context


class PagerQueryMixin:
    """Adds `pager_query` — the current querystring minus `page`, prefixed
    with '&' — so admin_panel/_pager.html links preserve active filters and
    search terms. Pairs with Django's built-in ListView pagination
    (`paginate_by`), which already supplies `page_obj`/`paginator`.
    """

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop('page', None)
        encoded = params.urlencode()
        context['pager_query'] = f'&{encoded}' if encoded else ''
        return context


class AdminListMixin(StaffRequiredMixin, PagerQueryMixin):
    """Base for every admin_panel list page."""
    paginate_by = 25


class BackURLMixin:
    """Resolves the Cancel/redirect target for form and delete views.

    `back_url_name` is a URL name in the `ap:` namespace. `get_back_url_args`
    supplies positional args for URLs that need a pk (e.g. a question's
    delete view cancels back to `ap:quiz_detail` with the quiz's pk) — kept
    positional rather than a keyword `pk=` because some of these targets
    take differently-named kwargs (`ap:choice_add` takes `question_pk`, not
    `pk`), and positional reversal works regardless of the kwarg's name.
    """
    back_url_name = ''

    def get_back_url_args(self):
        return []

    def get_success_url(self):
        return reverse(self.back_url_name, args=self.get_back_url_args())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['back_url'] = self.back_url_name
        back_args = self.get_back_url_args()
        if back_args:
            context['back_pk'] = back_args[0]
        return context


class AdminFormMixin(StaffRequiredMixin, BackURLMixin):
    """Shared plumbing for admin_panel/form.html create/update views.

    `context_object_name = 'obj'` is what lets form.html tell create and
    update apart with `{% if obj %}`: CreateView's `self.object` is None on
    GET, so SingleObjectMixin never adds the key at all (undefined is falsy
    in a template); UpdateView's `self.object` is always the fetched
    instance, so `obj` is truthy.
    """
    template_name = 'admin_panel/form.html'
    context_object_name = 'obj'
    subtitle = ''
    help_text = ''
    title = ''

    def get_title(self):
        return self.title

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'title': self.get_title(),
            'subtitle': self.subtitle,
            'help_text': self.help_text,
        })
        return context


class AdminDeleteMixin(StaffRequiredMixin, BackURLMixin):
    """Shared plumbing for admin_panel/confirm_delete.html delete views."""
    template_name = 'admin_panel/confirm_delete.html'
    context_object_name = 'obj'
    obj_type = ''
    success_message = 'Deleted.'

    def get_success_message(self):
        # `success_message` is a %-format string. Every real field on the
        # instance is available by name (e.g. "%(title)s"), plus `%(obj)s`
        # for str(instance) — covers every message text the old function
        # views used to hand-format.
        fields = {**self.object.__dict__, 'obj': str(self.object)}
        return self.success_message % fields

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['obj_type'] = self.obj_type
        return context

    def get_success_url(self):
        # DeletionMixin.form_valid calls get_success_url() *before* deleting
        # self.object, so the message can still safely read its fields here.
        messages.success(self.request, self.get_success_message())
        return super().get_success_url()
