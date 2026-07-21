# Third-party notices

The root [`LICENSE`](LICENSE) applies to Beacon-authored code only. Files
listed below remain under their original licenses; those license texts take
precedence for the corresponding files.

## Vendored MediaServer source

`MediaServer/source/` is derived from
[ZLMediaKit](https://github.com/ZLMediaKit/ZLMediaKit). Its
[`LICENSE`](MediaServer/source/LICENSE) is an MIT-like license with an
additional obligation to preserve ZLMediaKit identification in fields such as
service titles, `Server`, and `User-Agent`. Redistributors must comply with
that additional condition.

The same tree vendors these upstream components:

| Component | Location | License |
|---|---|---|
| ZLToolKit | `MediaServer/source/3rdpart/ZLToolKit/` | MIT |
| media-server | `MediaServer/source/3rdpart/media-server/` | MIT |
| JsonCpp | `MediaServer/source/3rdpart/jsoncpp/` | Public Domain / MIT |
| wepoll | `MediaServer/source/3rdpart/wepoll/` | BSD 2-Clause-like |
| Swagger UI 5.10.3 | `MediaServer/source/www/swagger/` | Apache-2.0 |

Complete license texts are stored in each listed directory. MediaServer also
contains upstream browser assets and generated API documentation; their
source headers and upstream notices must be retained. The bundled
`ZLMRTCClient.js` carries its source and dependency licenses in
[`ZLMRTCClient.LICENSES.md`](MediaServer/source/www/ZLMRTCClient.LICENSES.md).
Swagger UI's `LICENSE` and `NOTICE` were restored from the matching
`swagger-ui-dist@5.10.3` package.

## Package dependencies

Python and JavaScript dependencies are installed from their package registries
and are not covered by Beacon's license. See `Admin/requirements-*.txt`,
`Admin/frontend/package-lock.json`, and the SDK manifests for the exact
dependency sets. `Admin/static/app-shell/` is generated from the frontend
lockfile and contains those JavaScript dependencies in bundled form. Its
generated `THIRD_PARTY_LICENSES.txt` carries the production package license
texts supplied by npm packages, plus license metadata and upstream links when a
package omits a standalone text. It must be shipped with the bundle.
Distributors of other binary bundles or containers remain responsible for
carrying any additional notices required by their included dependencies.

## Analyzer utility code

`Analyzer/Analyzer/Core/Utils/Base64.h` is an altered form of René
Nyffenegger's Base64 implementation. Its zlib-style license notice, including
the requirement to preserve that notice and mark altered versions, is retained
at the top of the source file.

## Models and proprietary SDKs

Model weights are intentionally not tracked. Users must obtain models under
terms that permit their intended use and distribution.

No EasyPlayer-Pro runtime is included. It requires a separate vendor license
for development or redistribution and must not be added to an open-source
release without documented redistribution rights.
