#include "YoloOutputLayout.h"

#include <algorithm>
#include <limits>

namespace AVSAnalyzer {
namespace {

static std::vector<int64_t> drop_batch_dim(const std::vector<int64_t>& shape) {
    if (shape.size() >= 3) {
        return std::vector<int64_t>(shape.begin() + 1, shape.end());
    }
    return shape;
}

static std::vector<int64_t> drop_ones_keep_order(const std::vector<int64_t>& dims) {
    std::vector<int64_t> out;
    out.reserve(dims.size());
    for (auto d : dims) {
        if (d > 1) {
            out.push_back(d);
        }
    }
    return out;
}

static bool safe_mul_i64(int64_t a, int64_t b, int64_t& out) {
    if (a == 0 || b == 0) {
        out = 0;
        return true;
    }
    if (a > 0 && b > 0 && a > (std::numeric_limits<int64_t>::max() / b)) {
        return false;
    }
    out = a * b;
    return true;
}

static bool is_reasonable_dim_candidate(int64_t d) {
    // YOLO dim is usually (4/5 + classes) or pose dim (56) — generally small-ish.
    if (d < 6) {
        return false;
    }
    if (d > 4096) {
        return false;
    }
    return true;
}

static bool is_expected_dim(int64_t d, int classCount) {
    if (d == 56) {
        return true;  // YOLOv8 pose (best-effort)
    }
    if (classCount > 0) {
        if (d == static_cast<int64_t>(4 + classCount)) {
            return true;
        }
        if (d == static_cast<int64_t>(5 + classCount)) {
            return true;
        }
    }
    return false;
}

}  // namespace

bool isValidYoloDetectionModelIo(
    size_t inputCount,
    size_t outputCount,
    int outputDim,
    int outputRows
) {
    return inputCount > 0 && outputCount > 0 && outputDim >= 5 && outputRows > 0;
}

bool parseYoloOutputLayout(
    const std::vector<int64_t>& shape,
    int classCount,
    YoloOutputLayout& out,
    std::string& errMsg
) {
    YoloOutputLayout tmp;
    errMsg.clear();

    if (shape.empty()) {
        errMsg = "shape is empty";
        return false;
    }

    std::vector<int64_t> dims = drop_batch_dim(shape);
    dims = drop_ones_keep_order(dims);

    if (dims.size() < 2) {
        errMsg = "shape has insufficient dims";
        return false;
    }

    // Common: only (dim, rows) or (rows, dim) after dropping ones.
    if (dims.size() == 2) {
        const int64_t a = dims[0];
        const int64_t b = dims[1];
        if (a <= 0 || b <= 0) {
            errMsg = "shape contains non-positive dims";
            return false;
        }
        if (a <= b) {
            tmp.dim = static_cast<int>(a);
            tmp.rows = static_cast<int>(b);
            tmp.rowsFirst = false;  // dim x rows
        } else {
            tmp.dim = static_cast<int>(b);
            tmp.rows = static_cast<int>(a);
            tmp.rowsFirst = true;   // rows x dim
        }
        out = tmp;
        return true;
    }

    // More dims: try to find which axis is `dim` and flatten the rest as `rows`.
    int dimAxis = -1;
    // Prefer expected dims at the ends (we can reshape/transpose cheaply).
    if (is_expected_dim(dims.front(), classCount)) {
        dimAxis = 0;
    } else if (is_expected_dim(dims.back(), classCount)) {
        dimAxis = static_cast<int>(dims.size() - 1);
    } else {
        // Scan for exact expected dim anywhere.
        for (size_t i = 0; i < dims.size(); ++i) {
            if (is_expected_dim(dims[i], classCount)) {
                dimAxis = static_cast<int>(i);
                break;
            }
        }
    }

    if (dimAxis < 0) {
        // Heuristic fallback: smallest reasonable dimension is likely dim.
        int64_t best = std::numeric_limits<int64_t>::max();
        for (size_t i = 0; i < dims.size(); ++i) {
            const int64_t d = dims[i];
            if (!is_reasonable_dim_candidate(d)) {
                continue;
            }
            if (d < best) {
                best = d;
                dimAxis = static_cast<int>(i);
            }
        }
    }

    if (dimAxis < 0) {
        errMsg = "cannot infer dim axis";
        return false;
    }

    const int64_t dim = dims[static_cast<size_t>(dimAxis)];
    if (dim <= 0) {
        errMsg = "dim is non-positive";
        return false;
    }

    // Fast-path: dim axis must be first or last for a zero-copy 2D view.
    if (dimAxis != 0 && dimAxis != static_cast<int>(dims.size() - 1)) {
        errMsg = "unsupported layout: dim axis is not first/last";
        return false;
    }

    int64_t rows64 = 1;
    for (size_t i = 0; i < dims.size(); ++i) {
        if (static_cast<int>(i) == dimAxis) {
            continue;
        }
        const int64_t d = dims[i];
        if (d <= 0) {
            errMsg = "shape contains non-positive dims";
            return false;
        }
        int64_t next = 0;
        if (!safe_mul_i64(rows64, d, next)) {
            errMsg = "rows overflow";
            return false;
        }
        rows64 = next;
    }

    if (rows64 <= 0 || rows64 > static_cast<int64_t>(std::numeric_limits<int>::max())) {
        errMsg = "rows out of range";
        return false;
    }
    if (dim > static_cast<int64_t>(std::numeric_limits<int>::max())) {
        errMsg = "dim out of range";
        return false;
    }

    tmp.rows = static_cast<int>(rows64);
    tmp.dim = static_cast<int>(dim);
    tmp.rowsFirst = (dimAxis == static_cast<int>(dims.size() - 1));  // dim last => rows-first

    out = tmp;
    return true;
}

bool selectYoloDetectionOutput(
    const std::vector<std::vector<int64_t>>& outputShapes,
    int classCount,
    size_t& selectedIndex,
    YoloOutputLayout& selectedLayout,
    std::string& errMsg
) {
    errMsg.clear();
    selectedIndex = 0;
    selectedLayout = YoloOutputLayout{};

    if (outputShapes.empty()) {
        errMsg = "no outputs";
        return false;
    }

    struct Candidate {
        size_t index = 0;
        YoloOutputLayout layout{};
        int score = 0;
    };

    Candidate best{};
    bool hasBest = false;

    const int v8Expected = (classCount > 0) ? (4 + classCount) : 0;
    const int v5Expected = (classCount > 0) ? (5 + classCount) : 0;

	    for (size_t i = 0; i < outputShapes.size(); ++i) {
	        const auto& shape = outputShapes[i];
	        YoloOutputLayout layout;
	        if (std::string perr; !parseYoloOutputLayout(shape, classCount, layout, perr)) {
	            continue;
	        }
	        if (layout.rows <= 0 || layout.dim <= 0) {
	            continue;
	        }

        int score = 0;
        // Prefer exact detection dims when classCount is known.
        if (classCount > 0) {
            if (layout.dim == v8Expected || layout.dim == v5Expected) {
                score += 900;
            } else if (layout.dim >= v8Expected) {
                // Seg models often append mask coefficients after class scores.
                // Give a high score if it at least has bbox+classes.
                const int extraV8 = layout.dim - v8Expected;
                const int extraV5 = layout.dim - v5Expected;
                if (extraV5 >= 0 && extraV5 <= 128) {
                    score += 800;  // bbox + obj + classes + extras
                } else if (extraV8 >= 0 && extraV8 <= 128) {
                    score += 700;  // bbox + classes + extras
                } else {
                    score += 600;
                }
            } else {
                // Too small to be bbox+classes (likely prototype/mask output).
                score += 100;
            }
        } else {
            // classCount unknown: best-effort heuristics.
            if (layout.dim >= 6) score += 150;
            if (layout.dim >= 20 && layout.dim <= 512) score += 200;
            if (layout.dim >= 50 && layout.dim <= 512) score += 250;
        }

        // Reasonable rows count bonus (avoid tiny aux outputs like [1, 100, 6]).
        if (layout.rows >= 100 && layout.rows <= 40000) {
            score += 50;
        }

        // Tie-breaker: prefer larger dim (prototype outputs are usually small dim like 32).
        score += std::min(layout.dim, 512);

        Candidate cand;
        cand.index = i;
        cand.layout = layout;
        cand.score = score;

        if (!hasBest || cand.score > best.score) {
            best = cand;
            hasBest = true;
        }
    }

    if (!hasBest) {
        errMsg = "no yolo-like output";
        return false;
    }

    selectedIndex = best.index;
    selectedLayout = best.layout;
    return true;
}

}  // namespace AVSAnalyzer
