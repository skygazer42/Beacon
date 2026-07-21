import os
import secrets

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from app.models import CloudEdgeCluster, CloudProject, CloudTenant
from app.utils.CloudEdgeAuth import hash_edge_token


def _env_str(name: str, default: str = "") -> str:
    """读取环境变量并转换为字符串。"""
    return str(os.environ.get(name, default) or "").strip()


def _env_str_default(name: str, default: str) -> str:
    """处理环境变量字符串默认。"""
    value = _env_str(name, "")
    return value or str(default)


def _ensure_admin_user(command: BaseCommand, *, username: str, password: str) -> None:
    """处理`ensure`管理员用户。"""
    if User.objects.filter(username=username).exists():
        command.stdout.write(f"admin user exists: {username} (password not changed)")
        return
    User.objects.create_superuser(username=username, password=password, email="")
    command.stdout.write(f"created admin user: {username}")


def _write_edge_token(command: BaseCommand, *, token_plain: str) -> None:
    """Write the one-time edge token only when an explicit secret path is configured."""
    token_file = _env_str("BEACON_BOOTSTRAP_EDGE_TOKEN_FILE", "")
    if not token_file:
        command.stdout.write("edge token was not exported; rotate it from the Cloud console before connecting an edge")
        return

    parent = os.path.dirname(token_file)
    if parent:
        os.makedirs(parent, mode=0o700, exist_ok=True)
    descriptor = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as f:
        f.write(token_plain + "\n")
    os.chmod(token_file, 0o600)
    command.stdout.write(f"wrote one-time edge token to configured secret file: {token_file}")


class Command(BaseCommand):
    help = "Cloud SaaS v1 初始化：创建 admin 用户 + default tenant/project/edge_cluster"

    def handle(self, *args, **options):
        """处理相关数据。"""
        mode = _env_str("BEACON_DEPLOYMENT_MODE", "").lower()
        if mode and mode not in ("cloud", "saas"):
            raise CommandError("beacon_cloud_bootstrap should only run in cloud mode")

        if not _env_str("BEACON_CLOUD_EDGE_TOKEN_PEPPER", ""):
            raise CommandError("missing BEACON_CLOUD_EDGE_TOKEN_PEPPER")

        username = _env_str_default("BEACON_BOOTSTRAP_ADMIN_USERNAME", "admin")
        password = _env_str("BEACON_BOOTSTRAP_ADMIN_PASSWORD", "")
        if not password:
            raise CommandError("missing BEACON_BOOTSTRAP_ADMIN_PASSWORD")
        if not settings.DEBUG:
            try:
                validate_password(password)
            except ValidationError as e:
                raise CommandError(
                    "BEACON_BOOTSTRAP_ADMIN_PASSWORD is not strong enough: " + "; ".join(e.messages)
                ) from e
        _ensure_admin_user(self, username=username, password=password)
       #云租户
        tenant, _ = CloudTenant.objects.get_or_create(
            slug="default",
            defaults={"name": "default", "enabled": True},
        )
        project, _ = CloudProject.objects.get_or_create(
            tenant=tenant,
            name="default",
            defaults={"enabled": True},
        )

        cluster_name = _env_str_default("BEACON_BOOTSTRAP_EDGE_CLUSTER_NAME", "edge-default")
        existing = CloudEdgeCluster.objects.filter(project=project, name=cluster_name).first()
        if existing:
            self.stdout.write(f"edge cluster exists: {existing.id} {existing.name} (token not rotated)")
            return

        token_plain = secrets.token_urlsafe(32)
        cluster = CloudEdgeCluster.objects.create(
            project=project,
            name=cluster_name,
            enabled=True,
            edge_token_hash=hash_edge_token(token_plain),
        )
        self.stdout.write(f"created edge cluster: {cluster.id} {cluster.name}")

        _write_edge_token(self, token_plain=token_plain)
