#include "hybrid_model.h"
#include <math.h>
#include <float.h>
#include <stddef.h>
#include <string.h>
/* Sticky errors: no allocation, process exit, or runtime I/O. */
static double OctaLink_Eps(double t) { return 16.0 * DBL_EPSILON * fabs(t); }
static void OctaLink_Error(OctaLink_State *st, int code, uint32_t block) {
    if (st->status == OCTALINK_OK) { st->status = code; st->error_block = block; }
}
static void OctaLink_Eval(OctaLink_State *st, double t, const double *x,
                          double *dx, int major, const int *hit) {
    double y[13];
    (void)t; (void)x; (void)hit; (void)major; (void)dx;
    y[0] = (t >= 1.0 ? 1.0 : 0.0);
    if (!isfinite(y[0])) { OctaLink_Error(st, OCTALINK_NONFINITE, 1U); return; }
    y[1] = (1.0 * x[1]);
    if (!isfinite(y[1])) { OctaLink_Error(st, OCTALINK_NONFINITE, 6U); return; }
    y[2] = st->delay[1];
    if (!isfinite(y[2])) { OctaLink_Error(st, OCTALINK_NONFINITE, 7U); return; }
    y[3] = 0.0 + y[0] - y[2];
    if (!isfinite(y[3])) { OctaLink_Error(st, OCTALINK_NONFINITE, 2U); return; }
    y[4] = 4.5 * y[3] + 2.7999999999999998 * x[2] + 1.2 * 50.0 * (y[3] - x[3]);
    if (!isfinite(y[4])) { OctaLink_Error(st, OCTALINK_NONFINITE, 3U); return; }
    y[5] = fmin(fmax(y[4], -6.0), 6.0);
    if (!isfinite(y[5])) { OctaLink_Error(st, OCTALINK_NONFINITE, 4U); return; }
    if (major && hit[0]) st->zoh[0] = y[5];
    y[6] = st->zoh[0];
    if (!isfinite(y[6])) { OctaLink_Error(st, OCTALINK_NONFINITE, 5U); return; }
    y[7] = y[0];
    if (!isfinite(y[7])) { OctaLink_Error(st, OCTALINK_NONFINITE, 8U); return; }
    y[8] = y[6];
    if (!isfinite(y[8])) { OctaLink_Error(st, OCTALINK_NONFINITE, 8U); return; }
    y[9] = y[1];
    if (!isfinite(y[9])) { OctaLink_Error(st, OCTALINK_NONFINITE, 8U); return; }
    y[10] = y[7];
    if (!isfinite(y[10])) { OctaLink_Error(st, OCTALINK_NONFINITE, 9U); return; }
    y[11] = y[8];
    if (!isfinite(y[11])) { OctaLink_Error(st, OCTALINK_NONFINITE, 9U); return; }
    y[12] = y[9];
    if (!isfinite(y[12])) { OctaLink_Error(st, OCTALINK_NONFINITE, 9U); return; }
    dx[0] = (-1.2 * x[0]) + (-1.0 * x[1]) + 1.0 * y[6];
    if (!isfinite(dx[0])) { OctaLink_Error(st, OCTALINK_NONFINITE, 6U); return; }
    dx[1] = (1.0 * x[0]) + 0.0 * y[6];
    if (!isfinite(dx[1])) { OctaLink_Error(st, OCTALINK_NONFINITE, 6U); return; }
    dx[2] = y[3];
    if (!isfinite(dx[2])) { OctaLink_Error(st, OCTALINK_NONFINITE, 3U); return; }
    dx[3] = 50.0 * (y[3] - x[3]);
    if (!isfinite(dx[3])) { OctaLink_Error(st, OCTALINK_NONFINITE, 3U); return; }
    if (major) {
        st->y_out[0] = y[10];
        st->y_out[1] = y[11];
        st->y_out[2] = y[12];
        if (hit[1]) st->pending[1] = y[1];
    }
}
static void OctaLink_Major(OctaLink_State *st) {
    int hit[2] = {0};
    double dx[4] = {0};
    double eps = OctaLink_Eps(st->t);
    (void)eps;
    if (fabs(st->t - (double)st->next_hit[0] * 0.14999999999999999) <= eps) {
        if (st->next_hit[0] == UINT64_MAX) { OctaLink_Error(st, OCTALINK_LIMIT, 5U); return; }
        hit[0] = 1; ++st->next_hit[0];
    }
    if (fabs(st->t - (double)st->next_hit[1] * 0.14999999999999999) <= eps) {
        if (st->next_hit[1] == UINT64_MAX) { OctaLink_Error(st, OCTALINK_LIMIT, 7U); return; }
        hit[1] = 1; ++st->next_hit[1];
        st->delay[1] = st->pending[1];
    }
    OctaLink_Eval(st, st->t, st->X, dx, 1, hit);
}
void OctaLink_Init(OctaLink_State *st) {
    if (!st) return;
    memset(st, 0, sizeof(*st));
    st->delay[1] = st->pending[1] = 0.0;
    OctaLink_Major(st);
}
double OctaLink_NextTime(const OctaLink_State *st, double stop) {
    double next, candidate, eps, grid;
    if (!st || st->status != OCTALINK_OK || !isfinite(stop) || stop < st->t) return NAN;
    if (stop == st->t) return stop;
    eps = OctaLink_Eps(stop);
    grid = floor((st->t + OctaLink_Eps(st->t)) / OCTALINK_MAX_DT) + 1.0;
    if (!isfinite(grid) || grid > 9007199254740991.0) return NAN;
    next = stop; candidate = grid * OCTALINK_MAX_DT;
    if (candidate > st->t + OctaLink_Eps(st->t) && candidate < next) next = candidate;
    candidate = (double)st->next_hit[0] * 0.14999999999999999;
    if (candidate > st->t + OctaLink_Eps(st->t) && candidate < next) next = candidate;
    candidate = (double)st->next_hit[1] * 0.14999999999999999;
    if (candidate > st->t + OctaLink_Eps(st->t) && candidate < next) next = candidate;
    candidate = 1.0;
    if (candidate > st->t + OctaLink_Eps(st->t) && candidate < next) next = candidate;
    if (1.0 > st->t && 1.0 <= stop && fabs(next - 1.0) <= eps) next = 1.0;
    if (fabs(stop - next) <= eps) next = stop;
    return next;
}
static int OctaLink_IsStepEvent(double t) {
    (void)t;
    if (t == 1.0) return 1;
    return 0;
}
void OctaLink_Step(OctaLink_State *st, double dt) {
    double k1[4] = {0}, k2[4] = {0}, k3[4] = {0}, k4[4] = {0}, tmp[4] = {0};
    double target, next, h, end;
    unsigned int substeps = 0;
    if (!st || st->status != OCTALINK_OK) return;
    target = st->t + dt;
    if (!isfinite(dt) || dt <= 0.0 || !isfinite(target) || target <= st->t) {
        OctaLink_Error(st, OCTALINK_BAD_DT, 0U); return;
    }
    while (st->t < target) {
        if (++substeps > OCTALINK_MAX_SUBSTEPS || st->step_idx == UINT32_MAX) {
            OctaLink_Error(st, OCTALINK_LIMIT, 0U); return;
        }
        next = OctaLink_NextTime(st, target);
        if (!isfinite(next) || next <= st->t) { OctaLink_Error(st, OCTALINK_LIMIT, 0U); return; }
        h = next - st->t;
        OctaLink_Eval(st, st->t, st->X, k1, 0, NULL);
        if (st->status) return;
        for (int i = 0; i < 4; ++i) tmp[i] = st->X[i] + 0.5 * h * k1[i];
        OctaLink_Eval(st, st->t + 0.5 * h, tmp, k2, 0, NULL);
        if (st->status) return;
        for (int i = 0; i < 4; ++i) tmp[i] = st->X[i] + 0.5 * h * k2[i];
        OctaLink_Eval(st, st->t + 0.5 * h, tmp, k3, 0, NULL);
        if (st->status) return;
        for (int i = 0; i < 4; ++i) tmp[i] = st->X[i] + h * k3[i];
        end = OctaLink_IsStepEvent(next) ? nextafter(next, st->t) : next;
        OctaLink_Eval(st, end, tmp, k4, 0, NULL);
        if (st->status) return;
        for (int i = 0; i < 4; ++i) {
            tmp[i] = st->X[i] + (h / 6.0) * (k1[i] + 2.0*k2[i] + 2.0*k3[i] + k4[i]);
            if (!isfinite(tmp[i])) { OctaLink_Error(st, OCTALINK_NONFINITE, 0U); return; }
        }
        for (int i = 0; i < 4; ++i) st->X[i] = tmp[i];
        st->t = next; ++st->step_idx;
        OctaLink_Major(st);
        if (st->status) return;
    }
}
