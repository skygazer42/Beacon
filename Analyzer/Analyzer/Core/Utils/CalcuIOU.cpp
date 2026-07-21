#include "CalcuIOU.h"
#include <array>
#include <cstdio>
#include <iostream>
#include <algorithm>
#include <cmath>

namespace AVSAnalyzer {
    constexpr int kMaxN = 256;

    constexpr double kEps = 1E-8;
    int sig(double d) {
        if (d > kEps) {
            return 1;
        }
        if (d < -kEps) {
            return -1;
        }
        return 0;
    }
    struct Point {
        double x;
        double y;
        Point() = default;
        Point(double x, double y) : x(x), y(y) {}

        friend bool operator==(const Point& lhs, const Point& rhs) {
            return sig(lhs.x - rhs.x) == 0 && sig(lhs.y - rhs.y) == 0;
        }
    };
    double cross(Point o, Point a, Point b) {  //叉积
        return (a.x - o.x) * (b.y - o.y) - (b.x - o.x) * (a.y - o.y);
    }
    double area(Point* ps, int n) {
        ps[n] = ps[0];
        double res = 0;
        for (int i = 0; i < n; i++) {
            res += ps[i].x * ps[i + 1].y - ps[i].y * ps[i + 1].x;
        }
        return res / 2.0;
    }
    int lineCross(Point a, Point b, Point c, Point d, Point& p) {
        double s1 = cross(a, b, c);
        double s2 = cross(a, b, d);
        if (sig(s1) == 0 && sig(s2) == 0) return 2;
        if (sig(s2 - s1) == 0) return 0;
        p.x = (c.x * s2 - d.x * s1) / (s2 - s1);
        p.y = (c.y * s2 - d.y * s1) / (s2 - s1);
        return 1;
    }
    //多边形切割
    //用直线ab切割多边形p，切割后的在向量(a,b)的左侧，并原地保存切割结果
    //如果退化为一个点，也会返回去,此时n为1
    void polygon_cut(Point* p, int& n, Point a, Point b, Point* pp) {
        int m = 0; p[n] = p[0];
        for (int i = 0; i < n; i++) {
            if (sig(cross(a, b, p[i])) > 0) pp[m++] = p[i];
            if (sig(cross(a, b, p[i])) != sig(cross(a, b, p[i + 1])))
                lineCross(a, b, p[i], p[i + 1], pp[m++]);
        }
        n = 0;
        for (int i = 0; i < m; i++)
            if (!i || !(pp[i] == pp[i - 1]))
                p[n++] = pp[i];
        while (n > 1 && p[n - 1] == p[0])n--;
    }
    //---------------华丽的分隔线-----------------//
    //返回三角形oab和三角形ocd的有向交面积,o是原点//
    double intersectArea(Point a, Point b, Point c, Point d) {
        Point o(0, 0);
        int s1 = sig(cross(o, a, b));
        int s2 = sig(cross(o, c, d));
        if (s1 == 0 || s2 == 0)return 0.0;//退化，面积为0
        if (s1 == -1) std::swap(a, b);
        if (s2 == -1) std::swap(c, d);
        std::array<Point, 10> p{ o, a, b };
        int n = 3;
        std::array<Point, kMaxN> pp;
        polygon_cut(p.data(), n, o, c, pp.data());
        polygon_cut(p.data(), n, c, d, pp.data());
        polygon_cut(p.data(), n, d, o, pp.data());
        double res = std::fabs(area(p.data(), n));
        if (s1 * s2 == -1) {
            res = -res;
        }
        return res;
    }
    //求两多边形的交面积
    double intersectArea(Point* ps1, int n1, Point* ps2, int n2) {
        if (area(ps1, n1) < 0) std::reverse(ps1, ps1 + n1);
        if (area(ps2, n2) < 0) std::reverse(ps2, ps2 + n2);
        ps1[n1] = ps1[0];
        ps2[n2] = ps2[0];
        double res = 0;
        for (int i = 0; i < n1; i++) {
            for (int j = 0; j < n2; j++) {
                res += intersectArea(ps1[i], ps1[i + 1], ps2[j], ps2[j + 1]);
            }
        }
        return res;//assumeresispositive!
    }

    double CalcuPolygonIOU(const std::vector<double>& p, const std::vector<double>& q) {
        std::array<Point, kMaxN> ps1;
        std::array<Point, kMaxN> ps2;
        if (p.size() < 6 || q.size() < 6 || (p.size() % 2) != 0 || (q.size() % 2) != 0) {
            return 0.0;
        }

        auto n1 = static_cast<int>(p.size() / 2);
        auto n2 = static_cast<int>(q.size() / 2);
        if (n1 < 3 || n2 < 3) {
            return 0.0;
        }

        // area() writes ps[n] = ps[0], so we must keep n <= maxn-1.
        n1 = std::max(3, std::min(n1, kMaxN - 1));
        n2 = std::max(3, std::min(n2, kMaxN - 1));

        for (int i = 0; i < n1; i++) {
            ps1[static_cast<size_t>(i)].x = p[i * 2];
            ps1[static_cast<size_t>(i)].y = p[i * 2 + 1];
        }
        for (int i = 0; i < n2; i++) {
            ps2[static_cast<size_t>(i)].x = q[i * 2];
            ps2[static_cast<size_t>(i)].y = q[i * 2 + 1];
        }
        double area1 = std::fabs(area(ps1.data(), n1));
        double area2 = std::fabs(area(ps2.data(), n2));
        if (area1 <= kEps || area2 <= kEps) {
            return 0.0;
        }

        double inter_area = intersectArea(ps1.data(), n1, ps2.data(), n2);
        double iou = inter_area / area2;
        if (iou < 0.0) {
            iou = 0.0;
        }
        if (iou > 1.0) {
            iou = 1.0;
        }

        return iou;
    }


}
