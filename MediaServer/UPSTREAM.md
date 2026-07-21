# MediaServer upstream provenance

`source/` is a vendored ZLMediaKit source snapshot, including the upstream
subprojects named in `source/.gitmodules`. It was first imported into this
repository by Beacon commit `84a3760b`.

The import did not preserve upstream Git metadata. A blob-level comparison
identifies
[ZLMediaKit `a050f38cc9cba243fd9486976cf3a3ecad7bc30b`](https://github.com/ZLMediaKit/ZLMediaKit/commit/a050f38cc9cba243fd9486976cf3a3ecad7bc30b)
(2025-05-11) as the closest verifiable base: 478 of the 486 paths shared by
that tree and the initial Beacon import are byte-identical. The eight shared
paths that already differed at import are `cmake/FindSDL2.cmake`, six files
under `src/Srt/`, and `www/webrtc/index.html`. Therefore the vendored tree is
not represented as a clean checkout of that commit.

The base commit records these nested dependency revisions:

| Dependency | Upstream revision | Initial import comparison |
|---|---|---|
| ZLToolKit | `8f25d13f49e016858fae88f1045786ce26611873` | All 121 imported files match. |
| media-server | `0658496d5fc7d238f41e10ea4d0a10113a8eed84` | 558 files match; 40 imported files differ and 25 upstream files were omitted. |
| JsonCpp | `69098a18b9af0c47549d9a271c054d13ca92b006` | All 129 imported files match; 123 upstream test fixtures were omitted. |
| zlm_webassist | `6689195ac89462d40accd88f13dfde58902da57b` | All 16 imported files matched; the optional bundle is excluded from the open-source tree. |

These comparisons describe the initial import, before later Beacon patches.
Beacon changes after the import are visible in this repository's history:

```bash
git log -- MediaServer/source
```

The open-source release also carries a small, reviewable patch set on top of
that snapshot:

- removes the bundled runtime development certificate (`source/default.pem`)
  and example API credentials;
- avoids printing generated API secrets and replaces unsafe test-string copy;
- invokes the OpenAPI generator without a command shell;
- removes the WebRTC demo's unpinned remote debug script; and
- runs the supplied Linux container as an unprivileged user with only the
  low-port bind capability on the MediaServer executable.

Keep these changes when comparing or updating the vendor tree.

`source/3rdpart/ZLToolKit/tests/ssl.p12` is the upstream, expired test
certificate used by ZLToolKit's SSL test targets. It is not copied into the
runtime image and must never be configured as a deployment certificate.

For the next upstream sync, record the upstream repository URL and full commit
SHA in this file, compare the complete vendor tree, and preserve
`source/LICENSE`, `source/AUTHORS`, and every nested dependency license. Do not
remove or replace ZLMediaKit identification fields; its supplemental license
condition requires them to remain intact.
