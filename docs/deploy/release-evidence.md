# 发布证据与供应链验证

Beacon 将“源码能下载”与“交付物可追溯、可验证”分开管理。仓库中的
`.github/workflows/release-evidence.yml` 在受信任的 Git 标签上生成一组不可覆盖的
源码发布证据；`.github/workflows/release-container.yml` 仅在正式 GitHub Release 发布
时构建并推送 GHCR 镜像，再以不可变 digest 生成和验证镜像证据。`tools/release_evidence.py`
负责校验版本/标签/commit 一致性，组装源码清单，并在上传前后重新验证文件成员、语义
和 SHA-256。

!!! warning "证据边界"
    自动流程只证明同一标签对应的**源码归档**和 GHCR `linux/amd64` Cloud 镜像。
    它不证明在其他机器手工组装的 Linux/Windows 二进制、其他架构容器、模型、
    TensorRT Engine 或客户配置。每个真实交付件都必须在其构建流水线中生成自己的
    SBOM、校验和和签名/attestation，并用目标硬件完成业务、容量、故障和回滚验收。

## 1. 自动生成的文件

对 `vX.Y.Z` 标签，工作流生成一个仅含下列文件的 evidence 目录：

| 文件 | 用途 |
|------|------|
| `Beacon-vX.Y.Z-source.tar.gz` | 从已验证标签 commit 通过 `git archive` 与 `gzip -n` 生成的源码归档 |
| `Beacon-vX.Y.Z.spdx.json` | Syft 生成的 JSON SPDX SBOM |
| `provenance.sigstore.json` | 源码归档的 Sigstore/SLSA provenance bundle |
| `sbom.sigstore.json` | 将同一源码归档与 SPDX SBOM 绑定的 Sigstore bundle |
| `provenance-verification.json` | 对 provenance bundle 执行 `gh attestation verify` 的 JSON 结果 |
| `sbom-verification.json` | 对 SPDX predicate 执行 `gh attestation verify` 的 JSON 结果 |
| `release-manifest.json` | 版本、标签、完整 commit、仓库、工作流运行 URL、角色、大小与 SHA-256 |
| `SHA256SUMS` | 上述所有内容文件及 manifest 的 SHA-256 |

工作流中的第三方 Actions 使用完整 commit SHA 固定，Syft 版本也显式固定。发布事件
会把同一证据先作为 90 天 Actions artifact 保存，再附加到 GitHub Release；上传不
使用 `--clobber`，同名资产已存在时会失败，不会静默替换历史证据。

同一发布事件还会把 `deploy/cloud-saas-v1/Dockerfile` 构建为
`ghcr.io/<owner>/<repo>:vX.Y.Z` 和 `:sha-<40 位 commit>`，但验收、部署和回滚必须使用
工作流输出的 `ghcr.io/<owner>/<repo>@sha256:<digest>`。容器工作流同时生成 BuildKit
registry SBOM/provenance、独立 SPDX SBOM、GitHub Sigstore provenance/SBOM attestation
及各自的验证记录。Release 中的容器证据包括：

SemVer 含 build metadata（例如 `v1.2.3+build.4`）时，OCI 版本标签把 `+` 映射为 `_`；
原始版本仍保存在 OCI version label、attestation `subject-version` 和证据 JSON 中。

| 文件 | 用途 |
|------|------|
| `container-release.json` | 镜像 digest、只读引用、标签、平台、源码 ref/commit 与工作流 URL |
| `container.spdx.json` | 对已推送 digest 扫描生成的 SPDX SBOM |
| `container-vulnerability-report.json` | 推送前对同一版本镜像执行 Trivy HIGH/CRITICAL 硬门禁的 JSON 结果 |
| `image-index.json` | Registry 返回的 OCI index，用于定位唯一的 `linux/amd64` manifest |
| `linux-amd64-manifest.json` | 平台 manifest；其 image config digest 必须与推送前 Trivy 扫描的本地镜像完全一致 |
| `container-provenance.sigstore.json` | 镜像 digest 的 Sigstore/SLSA provenance bundle |
| `container-sbom.sigstore.json` | 镜像 digest 与独立 SPDX SBOM 的 Sigstore bundle |
| `container-provenance-verification.json` | 限定 tag、commit 和 predicate 的 provenance 验证记录 |
| `container-sbom-verification.json` | 限定 tag、commit 和 predicate 的 SBOM 验证记录 |
| `SHA256SUMS.container` | 上述容器证据文件的 SHA-256 |

容器证据文件统一使用 `container-` 前缀，避免与同一个 GitHub Release 中的源码
attestation 资产重名。两个工作流都禁止覆盖已有资产；名称空间也是发布原子性门禁，
不得为了绕过上传失败而增加 `--clobber`。

## 2. 发布前提与触发方式

正式发布前必须先满足：

1. 根目录 `PROJECT_VERSION`、发布标签和更新日志一致；标签必须为受支持的 SemVer，
   例如 `v1.2.3`。
2. 标签指向拟发布的完整 commit，受跟踪文件没有本地修改。
3. 主 CI、Python/npm 审计、Cloud 镜像 Trivy HIGH/CRITICAL 扫描、静态分析、目标平台
   构建和上线清单中的其他硬门禁全部通过。
4. 仓库规则保护 `main` 和发布标签；`.github/workflows/**` 的变更需要指定维护者审查，
   发布权限和 GitHub `release` environment 的审批人按组织制度配置。

仓库内的 `.github/CODEOWNERS` 已为工作流、发布证据、安全策略和部署资源指定维护者；
但该文件本身不会强制审批。远端分支规则仍必须启用“Require review from Code Owners”，
并保护 `CODEOWNERS` 与规则配置不被未经审批的提交绕过。

两个发布工作流还会同时读取分页 Release 列表与 `releases/latest`，执行
`validate-history`：每个已发布 Release 都必须使用受支持的严格 SemVer 标签、保留可
解析到 commit 的同名 Git tag，并且新版本的 SemVer precedence 必须严格高于其他已
发布版本。列表与 latest 视图不一致时两边取并集验证，因此已删除 tag 的“幽灵 Release”、
旧版本线回退或非标准版本号都会使发布失败，必须先由仓库所有者完成版本治理。

触发有两种：

- 发布 GitHub Release 时，源码与容器工作流自动运行。源码只有 `build-evidence` 成功才
  会附加到 Release；容器只有推送、SBOM、签名和按 digest 复验全部成功才会附加证据。
- 手工 `workflow_dispatch` 用于发布前预检。必须在 Actions 页面把运行 ref 选择为目标
  标签，并把 `tag` 输入为同一个值；如果从分支运行，即使分支恰好指向同一 commit，
  `source_ref` 策略验证仍会失败。手工预检只上传 Actions artifact，不修改 Release。

`validate-ref` 可以在独立、干净的标签工作树中先执行：

```bash
python tools/release_evidence.py validate-ref \
  --root . \
  --tag v1.2.3 \
  --commit "$(git rev-parse 'HEAD^{commit}')"
```

该命令要求 `PROJECT_VERSION == tag`、标签与 `HEAD` 指向同一 commit、工作树中的受
跟踪与未跟踪文件都为空，并确认 `LICENSE`、`THIRD_PARTY_NOTICES.md` 和 `SECURITY.md`
存在。未跟踪文件也会被拒绝，因为它们可能进入 Docker build context，造成镜像内容与
标签源码不一致。

如需在打标签前复核远端历史，可先导出与工作流相同的两个 API 视图，再离线运行门禁：

```bash
gh api --paginate 'repos/skygazer42/Beacon/releases?per_page=100' \
  | jq -s 'add // []' > published-releases.json
gh api 'repos/skygazer42/Beacon/releases/latest' > latest-release.json
python tools/release_evidence.py validate-history \
  --root . \
  --tag v1.2.3 \
  --releases published-releases.json \
  --latest-release latest-release.json
```

仓库从未发布 Release 时，`latest-release.json` 使用 JSON `null`。上述 JSON 只用于临时
验收，不应提交到仓库。

## 3. 下载后验证

始终把证据下载到一个新的专用目录；`verify` 会拒绝额外文件、缺失文件、符号链接、
大小或哈希变化、无包清单的 SPDX、非 Sigstore bundle、错误 predicate 以及不安全的
源码归档路径。

```bash
release_tag=v1.2.3
mkdir "Beacon-${release_tag}-evidence"

gh release download "${release_tag}" \
  --repo skygazer42/Beacon \
  --dir "Beacon-${release_tag}-evidence" \
  --pattern "Beacon-${release_tag}-source.tar.gz" \
  --pattern "Beacon-${release_tag}.spdx.json" \
  --pattern "*.sigstore.json" \
  --pattern "*-verification.json" \
  --pattern "release-manifest.json" \
  --pattern "SHA256SUMS"

python tools/release_evidence.py verify \
  --directory "Beacon-${release_tag}-evidence"

(cd "Beacon-${release_tag}-evidence" && sha256sum --check SHA256SUMS)
```

然后从 `release-manifest.json` 读取 `commit`，在线验证 provenance：

```bash
release_commit='<release-manifest.json 中的 40 位 commit>'

gh attestation verify \
  "Beacon-${release_tag}-evidence/Beacon-${release_tag}-source.tar.gz" \
  --repo skygazer42/Beacon \
  --source-ref "refs/tags/${release_tag}" \
  --source-digest "${release_commit}" \
  --signer-workflow "skygazer42/Beacon/.github/workflows/release-evidence.yml" \
  --predicate-type "https://slsa.dev/provenance/v1"
```

无法访问 GitHub Attestations API 时，可使用随包 bundle 做离线验证；验证工具仍需拥有
可信 Sigstore root：

```bash
gh attestation verify \
  "Beacon-${release_tag}-evidence/Beacon-${release_tag}-source.tar.gz" \
  --repo skygazer42/Beacon \
  --bundle "Beacon-${release_tag}-evidence/provenance.sigstore.json" \
  --source-ref "refs/tags/${release_tag}" \
  --source-digest "${release_commit}" \
  --signer-workflow "skygazer42/Beacon/.github/workflows/release-evidence.yml" \
  --predicate-type "https://slsa.dev/provenance/v1"

gh attestation verify \
  "Beacon-${release_tag}-evidence/Beacon-${release_tag}-source.tar.gz" \
  --repo skygazer42/Beacon \
  --bundle "Beacon-${release_tag}-evidence/sbom.sigstore.json" \
  --source-ref "refs/tags/${release_tag}" \
  --source-digest "${release_commit}" \
  --signer-workflow "skygazer42/Beacon/.github/workflows/release-evidence.yml" \
  --predicate-type "https://spdx.dev/Document"
```

验证记录必须与交付审批一同归档。不要只核对 Release 页面显示的版本名，也不要只运行
`sha256sum`：哈希只能发现内容变化，签名/attestation 才能验证来源身份与构建上下文。

容器使用 `container-release.json` 中的 `immutableReference` 验证和部署，不要从可变标签
反查 digest。以下命令同时限定仓库、发布 tag 和源码 commit：

```bash
image_ref='ghcr.io/skygazer42/beacon@sha256:<container-release.json 中的 digest>'

gh attestation verify "oci://${image_ref}" \
  --repo skygazer42/Beacon \
  --source-ref "refs/tags/${release_tag}" \
  --source-digest "${release_commit}" \
  --signer-workflow "skygazer42/Beacon/.github/workflows/release-container.yml" \
  --predicate-type "https://slsa.dev/provenance/v1"

gh attestation verify "oci://${image_ref}" \
  --repo skygazer42/Beacon \
  --source-ref "refs/tags/${release_tag}" \
  --source-digest "${release_commit}" \
  --signer-workflow "skygazer42/Beacon/.github/workflows/release-container.yml" \
  --predicate-type "https://spdx.dev/Document"
```

## 4. 平台与信任限制

GitHub Artifact Attestations 在公开 GitHub.com 仓库可用；私有/内部仓库需要相应的
GitHub Enterprise Cloud 能力，GitHub Enterprise Server 当前不支持。GHES 或完全
离线交付必须改用组织批准的内部构建机、制品库和签名体系（例如内部 Sigstore/Cosign
信任根），并保留等价的身份、来源 ref、commit、SBOM 和验证证据；不能把本工作流
跳过后仍判定供应链门禁通过。

当前固定的 checkout、setup、attestation、artifact upload/download Actions 均属于
Node.js 24 代际，采用自托管 runner 时必须满足各 Action 声明的最低 runner 版本。
GitHub-hosted `ubuntu-24.04` 由 GitHub 维护；切换 runner 镜像或 Action/Syft 版本属于
证据链变更，必须重新审查并执行预检。

官方参考：

- [GitHub Artifact Attestations 概念](https://docs.github.com/en/actions/concepts/security/artifact-attestations)
- [使用 Artifact Attestations 建立构建来源](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)
- [`gh attestation verify` 参数与策略](https://cli.github.com/manual/gh_attestation_verify)
- [`actions/attest` 模式、权限与平台限制](https://github.com/actions/attest)
- [Anchore SBOM Action](https://github.com/anchore/sbom-action)
