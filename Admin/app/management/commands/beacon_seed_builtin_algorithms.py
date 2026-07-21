from django.core.management.base import BaseCommand

from app.models import AlgorithmModel
from app.utils.BuiltinAlgorithms import list_builtin_algorithms


def _select_builtin_metas(*, seed_all: bool):
    """选择`builtin``metas`。"""
    all_metas = list_builtin_algorithms()
    if seed_all:
        return all_metas

    # 默认只导入“可售卖 SKU 包”相关内置算法：license_package != core
    return [m for m in all_metas if str(m.get("license_package") or "").strip() not in ("", "core")]


def _normalize_builtin_meta(meta: dict):
    """执行归一化`builtin`元数据。"""
    code = str(meta.get("code") or "").strip()
    if not code:
        return None

    name = str(meta.get("name") or code).strip() or code
    pkg = str(meta.get("license_package") or "core").strip() or "core"

    object_names = meta.get("object_names") if isinstance(meta.get("object_names"), list) else []
    object_names = [str(x).strip() for x in object_names if str(x).strip()]

    algorithm_subtype = str(meta.get("algorithm_subtype") or "").strip() or "detection"

    rel = str(meta.get("relative_model_path") or "").strip()
    remark = "内置算法模板（由命令生成）。"
    if rel:
        remark += " 需要在 Analyzer.modelDir 下提供模型文件: %s" % rel

    return {
        "code": code,
        "name": name,
        "pkg": pkg,
        "algorithm_subtype": algorithm_subtype,
        "object_str": ",".join(object_names),
        "object_count": len(object_names),
        "remark": remark,
    }


def _maybe_update_existing(existing, *, pkg: str, algorithm_subtype: str, force: bool, dry_run: bool) -> bool:
    """按需更新现有。"""
    current_pkg = str(getattr(existing, "license_package", "") or "core").strip() or "core"
    current_subtype = str(getattr(existing, "algorithm_subtype", "") or "detection").strip() or "detection"

    needs_pkg_update = bool(force or (current_pkg in ("", "core") and pkg != current_pkg))
    needs_subtype_update = bool(force or (current_subtype == "detection" and algorithm_subtype != current_subtype))

    if not (needs_pkg_update or needs_subtype_update):
        return False

    if not dry_run:
        if needs_pkg_update:
            existing.license_package = pkg
        if needs_subtype_update:
            existing.algorithm_subtype = algorithm_subtype
        existing.save()

    return True


def _create_algorithm_from_meta(row: dict, *, dry_run: bool) -> None:
    """创建算法`from`元数据。"""
    if dry_run:
        return

    AlgorithmModel.objects.create(
        sort=0,
        code=row.get("code") or "",
        name=row.get("name") or "",
        algorithm_subtype=row.get("algorithm_subtype") or "detection",
        object_count=int(row.get("object_count") or 0),
        object_str=row.get("object_str") or "",
        max_control_count=0,
        license_package=row.get("pkg") or "core",
        remark=row.get("remark") or "",
        state=1,
    )



class Command(BaseCommand):
    help = "Seed Analyzer built-in algorithms into Admin DB and apply default license_package SKU mapping."

    def add_arguments(self, parser):
        """处理新增`arguments`。"""
        parser.add_argument(
            "--all",
            action="store_true",
            help="Seed full built-in catalog (including core/COCO80). Default seeds only sellable SKU algorithms (non-core).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Override license_package even when already set (use with caution).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print changes without writing to DB.",
        )

    def handle(self, *args, **options):
        """处理相关数据。"""
        seed_all = bool(options.get("all"))
        force = bool(options.get("force"))
        dry_run = bool(options.get("dry_run"))

        metas = _select_builtin_metas(seed_all=seed_all)
        created = 0
        updated = 0
        skipped = 0

        for meta in metas:
            row = _normalize_builtin_meta(meta if isinstance(meta, dict) else {})
            if not row:
                continue

            existing = AlgorithmModel.objects.filter(code=row["code"]).order_by("id").first()
            if existing:
                did_update = _maybe_update_existing(
                    existing,
                    pkg=row["pkg"],
                    algorithm_subtype=row["algorithm_subtype"],
                    force=force,
                    dry_run=dry_run,
                )
                if did_update:
                    updated += 1
                else:
                    skipped += 1
                continue

            _create_algorithm_from_meta(row, dry_run=dry_run)
            created += 1

        self.stdout.write(
            "builtin algorithm seed done: scope=%s created=%d updated=%d skipped=%d dry_run=%s"
            % ("all" if seed_all else "sku_only", created, updated, skipped, str(dry_run))
        )
