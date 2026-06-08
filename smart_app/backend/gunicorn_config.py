import os
import logging
import multiprocessing

bind = "0.0.0.0:5000"

# workers = multiprocessing.cpu_count() * 2 + 1
workers = 1
worker_class = "gevent"
# worker_class = "geventwebsocket.gunicorn.workers.GeventWebSocketWorker"

worker_connections = 2000

backlog = 2048
timeout = 60
graceful_timeout = 30
keepalive = 5

max_requests = 1000
max_requests_jitter = 10

preload_app = False

accesslog = "-"
errorlog = "-"
loglevel = "info"

capture_output = False

access_log_format = ('%(h)s %(l)s %(u)s %(t)s ''"%(r)s" %(s)s %(b)s ''"%(f)s" "%(a)s"')

capture_output = True

limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190

reload = False