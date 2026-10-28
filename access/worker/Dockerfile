FROM debian:trixie-slim
ARG VCS_REF=unknown
LABEL org.opencontainers.image.revision=$VCS_REF
RUN apt-get update && apt-get install -y --no-install-recommends chromium xvfb x11vnc openbox socat python3 fonts-liberation ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 31000 access && useradd -u 31000 -g 31000 -d /tmp/home access
COPY worker/start.py worker/openbox.xml /opt/access/
USER 31000:31000
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python3", "/opt/access/start.py"]
