FROM python@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a

COPY components/control-plane/requirements-account-api.txt /tmp/requirements-account-api.txt
RUN pip install --no-cache-dir -r /tmp/requirements-account-api.txt
COPY components/control-plane/*.py /app/
COPY components/control-plane/django_api/ /app/django_api/
COPY components/admin-ui/ /ui/
RUN mkdir -p /run/keeplane-secrets /gateway-config

USER 65532:65532
CMD ["python", "/app/server.py"]
