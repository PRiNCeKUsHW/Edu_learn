web: python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn elearn_project.wsgi --bind 0.0.0.0:$PORT --workers 3
