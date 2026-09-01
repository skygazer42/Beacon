FROM python:3.14-alpine3.23@sha256:f734ffac635afd3bf15f0cc9a2ced79bc5d736aa6eb6a3d96337cfd5af8c9988 AS python-base
FROM ghcr.io/astral-sh/uv:0.12.8@sha256:d1cbaeadc234fe19c0d93daabcf5e98738cd93c6d1dd4918ef6aa30735feb23a AS uv
FROM python-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    BEACON_ROOT_DIR=/app/data \
    BEACON_CONFIG_PATH=/app/config.json

WORKDIR /app

# Apply published Alpine security fixes without retaining the package index.
RUN apk upgrade --no-cache

# 仅安装 Cloud 运行时依赖（避免 opencv/numpy）
COPY Admin/requirements-cloud.txt /tmp/requirements-cloud.txt
COPY Admin/requirements-cloud.lock /tmp/requirements-cloud.lock
COPY deploy/cloud-saas-v1/scripts/verify_requirements_lock.py /tmp/verify_requirements_lock.py
RUN --mount=type=bind,from=uv,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    python /tmp/verify_requirements_lock.py \
        /tmp/requirements-cloud.txt /tmp/requirements-cloud.lock \
    && UV_LINK_MODE=copy UV_HTTP_TIMEOUT=120 UV_HTTP_RETRIES=20 UV_NO_PROGRESS=1 \
        uv pip install --system --require-hashes --no-build \
        -r /tmp/requirements-cloud.lock \
    && python -m pip check \
    && python -m pip uninstall --yes pip

RUN addgroup -S -g 10001 beacon \
    && adduser -S -D -H -u 10001 -G beacon beacon

# 只拷贝 Cloud POC 运行所需的代码/脚本（减少镜像体积）
COPY --chown=beacon:beacon Admin /app/Admin
# Keep the image's fallback configuration Cloud-safe as well.  Compose and
# Helm mount their own config at this path, but a missing mount must not fall
# back to Edge paths under the read-only application tree.
COPY --chown=beacon:beacon --chmod=0444 deploy/cloud-saas-v1/config.cloud.json /app/config.json
COPY --chown=beacon:beacon PROJECT_VERSION /app/PROJECT_VERSION
COPY --chown=beacon:beacon deploy/cloud-saas-v1 /app/deploy/cloud-saas-v1
COPY --chown=beacon:beacon LICENSE THIRD_PARTY_NOTICES.md /licenses/Beacon/

# Normalize CRLF -> LF for shell scripts to avoid "bad interpreter" / `set: -\r` failures
# when building on Windows checkouts.
RUN sed -i 's/\r$//' /app/deploy/cloud-saas-v1/scripts/*.sh \
    && chmod +x /app/deploy/cloud-saas-v1/scripts/*.sh \
    && mkdir -p /app/Admin/staticfiles /app/data /demo \
    && BEACON_DJANGO_SECRET_KEY=build-only-not-for-runtime-7mQ2xV9pL4nR8sT5 \
        BEACON_DJANGO_DEBUG=0 \
        BEACON_DJANGO_ALLOWED_HOSTS=build.invalid \
        python /app/Admin/manage.py collectstatic --noinput \
    && chown -R beacon:beacon /app/Admin/staticfiles /app/data /demo

ARG BEACON_IMAGE_VERSION=development
ARG BEACON_IMAGE_REVISION=unknown
ARG BEACON_IMAGE_CREATED=1970-01-01T00:00:00Z
ARG BEACON_IMAGE_SOURCE=https://github.com/skygazer42/Beacon
LABEL org.opencontainers.image.title="Beacon Cloud SaaS v1" \
    org.opencontainers.image.description="Beacon cloud control plane and edge simulator runtime" \
    org.opencontainers.image.version="${BEACON_IMAGE_VERSION}" \
    org.opencontainers.image.revision="${BEACON_IMAGE_REVISION}" \
    org.opencontainers.image.created="${BEACON_IMAGE_CREATED}" \
    org.opencontainers.image.source="${BEACON_IMAGE_SOURCE}" \
    org.opencontainers.image.licenses="MIT"

USER 10001:10001

# 默认启动 Cloud Admin；edge-simulator 会在 compose.yml 里覆盖 command
CMD ["/app/deploy/cloud-saas-v1/scripts/entrypoint.sh"]
