# App image file permissions

Run `python -m pytest tests/integration/test_app_image_permissions.py -m live`
after building the admin UI. Cache the pinned base image and account API
requirements layer first, or allow their declared install-time registry access.
The fixture disables networking for the running container.

- Package the actual app and UI with directories set to 0700 and files to 0600, keeping the
  dependency requirements at 0644 so the existing install layer can be reused.
- The image runs as UID 65532, loads its actual Gunicorn configuration and reads
  the compiled UI, fonts and app files. Public files remain owned by root and
  cannot be changed by the application user.
- Remove the disposable container, build context and image after success or
  failure. Keep diagnostics outside Git and leave existing previews unchanged.
