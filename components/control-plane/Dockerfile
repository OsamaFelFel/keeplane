FROM python@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a AS core

COPY components/control-plane/requirements-account-api.txt /tmp/requirements-account-api.txt
RUN pip install --no-cache-dir -r /tmp/requirements-account-api.txt
COPY components/control-plane/ /app/
COPY components/admin-ui/ /ui/
RUN mkdir -p /run/keeplane-secrets /gateway-config \
    && chmod -R a+rX,go-w /app /ui
WORKDIR /app

USER 65532:65532
CMD ["gunicorn", "--config", "config/gunicorn.conf.py", "config.wsgi:application"]

# Optional shared-database package. The default target remains the preview.
FROM python@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a AS postgres-build
USER 0
COPY components/control-plane/licenses/ /usr/share/keeplane/licenses/
COPY components/control-plane/package_postgres.py /tmp/package_postgres.py
RUN apk add --no-cache libpq-dev=18.6-r0 gcc=15.2.0-r5 musl-dev=1.2.6-r2 \
    && pip install --no-cache-dir setuptools==80.9.0 \
    && python /tmp/package_postgres.py build

FROM core AS postgres
USER 0
COPY --from=postgres-build /usr/share/keeplane /usr/share/keeplane
COPY --from=postgres-build /wheels /wheels
COPY components/control-plane/package_postgres.py /tmp/package_postgres.py
RUN apk add --no-cache libpq=18.6-r0 \
    && pip install --no-index --no-deps --no-cache-dir /wheels/*.whl \
    && python /tmp/package_postgres.py inventory \
    && rm -r /wheels /tmp/package_postgres.py \
    && python /app/remove_runtime_installers.py
ENV PYTHONDONTWRITEBYTECODE=1
USER 65532:65532

FROM core AS preview
USER 0
RUN python /app/remove_runtime_installers.py
USER 65532:65532
