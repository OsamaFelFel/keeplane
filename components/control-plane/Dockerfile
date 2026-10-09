FROM python@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a

COPY components/control-plane/*.py /app/
COPY components/admin-ui/ /ui/

USER 65532:65532
CMD ["python", "/app/server.py"]
