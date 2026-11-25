FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml README.md LICENSE NOTICE.md ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip setuptools wheel &&     pip install --no-cache-dir --no-deps -e .
EXPOSE 8787
ENTRYPOINT ["openagent"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8787"]
