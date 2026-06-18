# CLI image (default target).
FROM python:3.12-slim AS cli
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .[excel]
ENTRYPOINT ["evbatt"]
CMD ["--help"]

# Optional explorer image:  docker build --target app -t evbatt-app .
FROM python:3.12-slim AS app
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY app ./app
RUN pip install --no-cache-dir .[excel] \
 && pip install --no-cache-dir -r app/requirements.txt
EXPOSE 8501
CMD ["streamlit", "run", "app/streamlit_app.py", \
     "--server.address=0.0.0.0", "--server.port=8501"]
