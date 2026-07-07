# PaceLab watch container (ADR-0013) — multi-arch base, runs on HermiPi (arm64, C-4).
FROM python:3.13-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# All state (results db, weather + FIT caches) lives under /data — mount a volume there.
WORKDIR /data
ENTRYPOINT ["pacelab"]
CMD ["watch"]
