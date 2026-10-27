FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Jakarta
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY network.json ./network.json
COPY bot.py .
USER 10001:10001
CMD ["python", "-u", "bot.py"]

FROM base AS test
COPY tests ./tests
COPY deploy/host_collector.py ./deploy/host_collector.py
CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]

FROM base AS production
ARG VCS_REF=development
LABEL org.opencontainers.image.source="https://github.com/2500018036-ship-it/nms-dashboard" \
      org.opencontainers.image.revision="${VCS_REF}"
