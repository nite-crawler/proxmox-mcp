FROM python:3.13-slim AS builder
WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.13-slim
RUN useradd --create-home --uid 10001 mcp
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels proxmox-ve-mcp
USER 10001
WORKDIR /home/mcp
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["proxmox-mcp"]
