bind = "0.0.0.0:3000"
workers = 1
threads = 8
timeout = 330
accesslog = "-"
errorlog = "-"
forwarded_allow_ips = ""
worker_tmp_dir = "/dev/shm"


def post_worker_init(worker):
    import os

    if os.environ.get("FIRST_ADMIN_PASSWORD_FILE"):
        from common.stores import stores
        from django.db import connections

        stores()
        connections.close_all()
