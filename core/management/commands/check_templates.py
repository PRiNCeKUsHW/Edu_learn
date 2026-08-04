from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.template import TemplateSyntaxError
from django.template.base import Lexer, TokenType
from django.template.loader import get_template

# Django's tag regex is not DOTALL, so a tag must open and close on the same
# line. An HTML formatter that line-wraps one leaves its opener stranded in a
# text node -- fatal for {% %}, but silently rendered as literal text for {{ }}.
ORPHAN_MARKERS = ("{{", "{%", "{#")


class Command(BaseCommand):
    help = (
        "Compile every template and flag tags split across lines. Catches both "
        "{% %} splits (which raise at render time) and {{ }} splits (which "
        "silently render as literal text)."
    )

    def handle(self, *args, **options):
        dirs = self._template_dirs()
        if not dirs:
            raise CommandError("No template directories found.")

        orphans = []
        syntax_errors = []
        checked = 0

        for directory in dirs:
            for path in sorted(directory.rglob("*.html")):
                checked += 1
                orphans.extend(self._find_orphan_tags(path))

                name = path.relative_to(directory).as_posix()
                try:
                    get_template(name)
                except TemplateSyntaxError as exc:
                    syntax_errors.append((name, exc))

        for path, lineno, snippet in orphans:
            self.stderr.write(
                self.style.ERROR(f"{path}:{lineno}: tag split across lines: {snippet}")
            )
        for name, exc in syntax_errors:
            self.stderr.write(self.style.ERROR(f"{name}: {exc}"))

        if orphans or syntax_errors:
            raise CommandError(
                f"{len(orphans)} split tag(s), "
                f"{len(syntax_errors)} syntax error(s) in {checked} template(s)."
            )

        self.stdout.write(self.style.SUCCESS(f"{checked} templates OK."))

    def _template_dirs(self):
        """Configured DIRS plus each app's templates/ dir."""
        dirs = []
        for engine in settings.TEMPLATES:
            dirs.extend(Path(d) for d in engine.get("DIRS", []))
        for entry in Path(settings.BASE_DIR).iterdir():
            candidate = entry / "templates"
            if candidate.is_dir():
                dirs.append(candidate)
        return [d for d in dict.fromkeys(dirs) if d.is_dir()]

    def _find_orphan_tags(self, path):
        """Tokenize with Django's own lexer and look for tag openers that ended
        up inside a text node -- the signature of a wrapped tag."""
        found = []
        source = path.read_text(encoding="utf-8")
        for token in Lexer(source).tokenize():
            if token.token_type != TokenType.TEXT:
                continue
            positions = [
                token.contents.find(m) for m in ORPHAN_MARKERS if m in token.contents
            ]
            if positions:
                start = min(positions)
                snippet = token.contents[start : start + 60]
                snippet = " ".join(snippet.split())
                found.append((path, token.lineno, snippet))
        return found
