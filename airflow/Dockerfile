# The official Airflow image plus uv, `make` and this project, so that a task runs the same
# command as the Makefile. Build context: the repository root (docker-compose.airflow.yml).
#
# The project has its own virtualenv (/opt/project-venv, from uv.lock, with the dbt group);
# Airflow keeps the Python environment of the base image. They never share packages.
# The tag follows the supported series, see DECISIONS.md #25.
FROM apache/airflow:3.3.2-python3.12

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends make \
 && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/project /opt/project-venv && chown -R airflow:root /opt/project /opt/project-venv

USER airflow
RUN pip install --no-cache-dir uv==0.12.16

# uv syncs once, here. A task never syncs, never downloads, never changes uv.lock.
ENV UV_PROJECT_ENVIRONMENT=/opt/project-venv \
    UV_PYTHON=/usr/local/bin/python \
    UV_PYTHON_DOWNLOADS=never \
    UV_FROZEN=1 \
    UV_NO_SYNC=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /opt/project
COPY --chown=airflow:root pyproject.toml uv.lock .python-version ./
RUN UV_NO_SYNC=0 uv sync --frozen --group dbt
COPY --chown=airflow:root . .
