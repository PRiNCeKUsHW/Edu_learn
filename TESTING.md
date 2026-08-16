# TESTING.md

## Framework

Django's built-in test runner (`django.test.TestCase` / `SimpleTestCase`),
run via `manage.py test`. No pytest, no `pytest-django` — there is no
`pytest.ini`/`pyproject.toml` in this repo, so don't assume pytest syntax
or fixtures work here. `freezegun` (in `requirements.txt`, test-only) is
used specifically for time-sensitive rate-limit assertions.

## Running Tests

```bash
python manage.py test                              # everything
python manage.py test accounts                     # one app
python manage.py test accounts.tests.test_auth      # one module
python manage.py test accounts.tests.test_auth.LoginTests   # one class
python manage.py test admin_panel                    # admin_panel/tests.py (single file, 630 lines)
```

No coverage tool is configured (no `coverage.py`/`pytest-cov` setup) — run
tests directly rather than assuming a coverage command exists. **No CI**
runs these automatically (no `.github/workflows/`); running the suite
before considering a change done is a manual step.

## Test Layout

Most apps use a `tests/` package (multiple focused modules); a few use a
single `tests.py`. Every app with real behavior has tests; `core` and
`discussions` (whose only logic — comment posting — actually lives in
`curriculum.views.lesson_detail`) do not need their own beyond what exists.

```
accounts/tests/
  test_auth.py           — LoginTests, RegistrationTests, LogoutTests, LoginRequiredPermissionTests
  test_account_settings.py — LoginRequiredTests, ProfileEditTests, PasswordChangeTests, AccountDeleteTests
  test_google_oauth.py   — GoogleOAuthMechanicsTests, GoogleLoginViewTests, GoogleCallbackViewTests,
                            GoogleCompleteProfileViewTests, GoogleLinkConfirmViewTests, RegressionTests
  test_ratelimit_ip.py   — GetClientIpTests, RateLimitProxyDifferentiationTests
  test_security.py       — LoginRedirectSecurityTests (open-redirect guard)

curriculum/tests/
  factories.py            — shared test data builders (Class/Subject/Chapter/Lesson etc.)
  test_hierarchy.py        — DynamicStructureTests, BrowsingTests, DashboardGroupingTests,
                              VisibilityTests, SearchScopeTests, NoHardcodedStructureTests
  test_comments.py         — CommentPostingTests
  test_search.py           — SearchTests
  test_quiz_buttons.py      — ChapterListQuizButtonTests, LessonDetailQuizButtonTests

progress/tests/
  test_progress.py        — MarkWatchedTests, DashboardCalculationTests
  test_security.py        — UnauthorizedAccessTests

quizzes/tests/
  test_quiz.py             — QuizScoringTests, QuizQueryCountTests, QuizDuplicateSlugTests, QuizRetakeHistoryTests

admin_panel/tests.py        — StaffGateTests, SubjectCRUDTests, ChapterSlugAutofillTests,
                              QuestionChoiceBackURLTests, ResourceFileCleanupTests, UserToggleGuardTests,
                              CourseKindCRUDTests, ClassCRUDTests, QuizCRUDTests, LessonCRUDTests,
                              LessonSlugCollisionTests, WriteActionPermissionTests, StudentReportTests

discussions/tests.py         — placeholder (no app-specific logic to test independently of curriculum)
elearn_project/tests.py       — DatabaseUrlParsingTests, EnsureLogDirTests (settings-level, no DB/request cycle)
```

## What's Actually Covered

Reading the class names above is a reliable map of intent, but the notable
*behavioral* coverage worth knowing about before touching related code:

- **Google OAuth**: the full mechanics (token exchange, ID token
  verification, state CSRF check) and every branch of the callback view
  (existing GoogleAccount, exactly-one-email-match linking, 0-or-2+-match
  fallback to new-user, unverified email rejection) — see
  `test_google_oauth.py`'s `RegressionTests` for previously-fixed bugs
  locked in.
- **Rate limiting**: real client-IP extraction behind a proxy
  (`X-Real-IP` vs `X-Forwarded-For` vs `REMOTE_ADDR`), and that two
  different IPs get independent buckets (`RateLimitProxyDifferentiationTests`)
  — this is the test class most likely to need `freezegun` if you touch
  rate-limit windows.
- **Curriculum hierarchy**: that nothing is hardcoded (`NoHardcodedStructureTests`),
  that `is_active` hides content at every level (`VisibilityTests`), that
  search stays scoped to active rows (`SearchScopeTests`), and dashboard
  grouping-by-kind behavior including the "hidden kind → ungrouped" case.
- **Quiz scoring**: correctness of scoring/pass logic, that retakes create
  new `QuizAttempt` rows rather than overwriting
  (`QuizRetakeHistoryTests`), duplicate-slug handling, and a query-count
  test (`QuizQueryCountTests`) guarding against an N+1 regression.
- **admin_panel**: staff gates on every CRUD surface (`StaffGateTests`,
  `WriteActionPermissionTests`), slug autofill/collision behavior
  (`ChapterSlugAutofillTests`, `LessonSlugCollisionTests`), that deleting a
  `Resource` also deletes its file from storage
  (`ResourceFileCleanupTests`), and the superuser-only guards on
  staff/active toggles (`UserToggleGuardTests`).
- **Account security**: login-required gates across the account settings
  surface, and the open-redirect guard on `?next=`
  (`LoginRedirectSecurityTests`).

## Fixtures / Factories

`curriculum/tests/factories.py` is the shared test-data builder for the
curriculum hierarchy (`Class`/`Subject`/`Chapter`/`Lesson`, etc.) — reuse it
rather than hand-building hierarchy rows in a new test. No Django fixture
files (`.json`) are used anywhere; all test data is built in Python.

## Before Merging a Change

- Run `python manage.py test` for the whole suite (there's no CI to catch
  a skipped run).
- If you touched a rate-limited view or the client-IP extraction logic,
  check whether the new/changed test needs `freezegun` to avoid a
  window-boundary flake (real epoch time backs `django-ratelimit`'s
  counters).
- If you touched a template, run `python manage.py check_templates` (see
  [DEVELOPMENT.md](DEVELOPMENT.md)) — not a test per se, but the fastest
  way to catch a formatter-mangled tag before it reaches a browser test.
- New views/models should land with tests in the owning app's `tests/`
  package, following the existing class-per-scenario naming pattern shown
  above.
