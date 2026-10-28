FROM python:3.12-slim
ARG VCS_REF=unknown
LABEL org.opencontainers.image.revision=$VCS_REF
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/access
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY theaz_access ./theaz_access
USER 31000:31000
CMD ["python", "-m", "theaz_access.gateway"]
