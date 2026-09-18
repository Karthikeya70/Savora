"""
Production Gunicorn config for Savora.

Run with:
  gunicorn -c gunicorn.conf.py "backend.app:app"

Requirements:
  pip install gunicorn uvicorn[standard]
"""
import multiprocessing

# Each uvicorn worker handles async I/O; 2*CPU+1 is the standard formula.
workers     = multiprocessing.cpu_count() * 2 + 1
worker_class = "uvicorn.workers.UvicornWorker"

bind        = "0.0.0.0:8000"
timeout     = 120          # seconds before killing a worker
keepalive   = 5            # seconds to keep idle connections alive

# Graceful restart: replace workers one by one without dropping requests.
max_requests        = 1000
max_requests_jitter = 100

accesslog = "-"   # stdout
errorlog  = "-"   # stderr
loglevel  = "info"
