# Runner for `make demo`: Python 3.12, the locked dependencies (runtime + dbt), the repo.
FROM python:3.12-slim
RUN pip install --no-cache-dir uv==0.12.16
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --group dbt
COPY . .
ENV PYTHONPATH=/app/src PATH="/app/.venv/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1
CMD ["python", "scripts/demo.py"]
