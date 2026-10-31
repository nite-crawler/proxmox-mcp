FROM python:3.15-slim@sha256:94d3426f1def7db4a106a232ac121bfd975393e5dfd40a619b955fae45fe7913 AS builder
WORKDIR /build
COPY requirements.lock requirements-build.lock ./
RUN python -m pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements-build.lock
RUN python -m venv /opt/venv && /opt/venv/bin/python -m pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.lock
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m build --wheel --no-isolation && /opt/venv/bin/python -m pip install --no-cache-dir --no-deps --no-index dist/*.whl
# Installers and their vendored dependencies are not needed at runtime.
RUN /opt/venv/bin/python -m pip uninstall --yes pip

FROM python:3.15-slim@sha256:94d3426f1def7db4a106a232ac121bfd975393e5dfd40a619b955fae45fe7913
RUN python -m pip uninstall --yes pip && rm -rf /usr/local/lib/python3.13/ensurepip
RUN useradd --create-home --uid 10001 mcp
COPY --from=builder /opt/venv /opt/venv
USER 10001
WORKDIR /home/mcp
ENV PYTHONUNBUFFERED=1
ENV PATH="/opt/venv/bin:$PATH"
ENTRYPOINT ["proxmox-mcp"]
