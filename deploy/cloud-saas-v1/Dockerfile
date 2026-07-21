FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    BEACON_ROOT_DIR=/app/data

WORKDIR /app

# 仅安装 Cloud 运行时依赖（避免 opencv/numpy）
COPY Admin/requirements-cloud.txt /tmp/requirements-cloud.txt
RUN python -m pip install --no-cache-dir --retries 10 --timeout 300 --prefer-binary \
    -r /tmp/requirements-cloud.txt

RUN addgroup --system --gid 10001 beacon \
    && adduser --system --uid 10001 --ingroup beacon --home /home/beacon --disabled-password beacon

# 只拷贝 Cloud POC 运行所需的代码/脚本（减少镜像体积）
COPY --chown=beacon:beacon Admin /app/Admin
COPY --chown=beacon:beacon config.json /app/config.json
COPY --chown=beacon:beacon PROJECT_VERSION /app/PROJECT_VERSION
COPY --chown=beacon:beacon deploy/cloud-saas-v1 /app/deploy/cloud-saas-v1

# Normalize CRLF -> LF for shell scripts to avoid "bad interpreter" / `set: -\r` failures
# when building on Windows checkouts.
RUN sed -i 's/\r$//' /app/deploy/cloud-saas-v1/scripts/*.sh \
    && chmod +x /app/deploy/cloud-saas-v1/scripts/entrypoint.sh \
    && chmod +x /app/deploy/cloud-saas-v1/scripts/minio_init.sh \
    && mkdir -p /app/Admin/staticfiles /app/data /demo \
    && chown -R beacon:beacon /app/Admin/staticfiles /app/data /demo

USER 10001:10001

# 默认启动 Cloud Admin；edge-simulator 会在 compose.yml 里覆盖 command
CMD ["/app/deploy/cloud-saas-v1/scripts/entrypoint.sh"]
