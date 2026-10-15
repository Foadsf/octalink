#include "mwe_dc_motor.h"
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
    double y[16];
    (void)t; (void)x; (void)hit; (void)major; (void)dx;
    y[0] = (t >= 0.0 ? 1.0 : 0.0);
    if (!isfinite(y[0])) { OctaLink_Error(st, OCTALINK_NONFINITE, 1U); return; }
    y[1] = x[0];
    if (!isfinite(y[1])) { OctaLink_Error(st, OCTALINK_NONFINITE, 5U); return; }
    y[2] = x[1];
    if (!isfinite(y[2])) { OctaLink_Error(st, OCTALINK_NONFINITE, 10U); return; }
    y[3] = 1.0 * y[1];
    if (!isfinite(y[3])) { OctaLink_Error(st, OCTALINK_NONFINITE, 6U); return; }
    y[4] = 0.01 * y[1];
    if (!isfinite(y[4])) { OctaLink_Error(st, OCTALINK_NONFINITE, 7U); return; }
    y[5] = 0.10000000000000001 * y[2];
    if (!isfinite(y[5])) { OctaLink_Error(st, OCTALINK_NONFINITE, 11U); return; }
    y[6] = 0.01 * y[2];
    if (!isfinite(y[6])) { OctaLink_Error(st, OCTALINK_NONFINITE, 12U); return; }
    y[7] = y[2];
    if (!isfinite(y[7])) { OctaLink_Error(st, OCTALINK_NONFINITE, 13U); return; }
    y[8] = y[1];
    if (!isfinite(y[8])) { OctaLink_Error(st, OCTALINK_NONFINITE, 13U); return; }
    y[9] = 0.0 + y[0] - y[3];
    if (!isfinite(y[9])) { OctaLink_Error(st, OCTALINK_NONFINITE, 2U); return; }
    y[10] = 0.0 + y[4] - y[5];
    if (!isfinite(y[10])) { OctaLink_Error(st, OCTALINK_NONFINITE, 8U); return; }
    y[11] = y[7];
    if (!isfinite(y[11])) { OctaLink_Error(st, OCTALINK_NONFINITE, 14U); return; }
    y[12] = y[8];
    if (!isfinite(y[12])) { OctaLink_Error(st, OCTALINK_NONFINITE, 14U); return; }
    y[13] = 0.0 + y[9] - y[6];
    if (!isfinite(y[13])) { OctaLink_Error(st, OCTALINK_NONFINITE, 3U); return; }
    y[14] = 100.0 * y[10];
    if (!isfinite(y[14])) { OctaLink_Error(st, OCTALINK_NONFINITE, 9U); return; }
    y[15] = 2.0 * y[13];
    if (!isfinite(y[15])) { OctaLink_Error(st, OCTALINK_NONFINITE, 4U); return; }
    dx[0] = y[15];
    if (!isfinite(dx[0])) { OctaLink_Error(st, OCTALINK_NONFINITE, 5U); return; }
    dx[1] = y[14];
    if (!isfinite(dx[1])) { OctaLink_Error(st, OCTALINK_NONFINITE, 10U); return; }
    if (major) {
        st->y_out[0] = y[11];
        st->y_out[1] = y[12];
    }
}
static void OctaLink_Major(OctaLink_State *st) {
    int hit[1] = {0};
    double dx[2] = {0};
    double eps = OctaLink_Eps(st->t);
    (void)eps;
    OctaLink_Eval(st, st->t, st->X, dx, 1, hit);
}
void OctaLink_Init(OctaLink_State *st) {
    if (!st) return;
    memset(st, 0, sizeof(*st));
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
    if (fabs(stop - next) <= eps) next = stop;
    return next;
}
static int OctaLink_IsStepEvent(double t) {
    (void)t;
    return 0;
}
void OctaLink_Step(OctaLink_State *st, double dt) {
    double k1[2] = {0}, k2[2] = {0}, k3[2] = {0}, k4[2] = {0}, tmp[2] = {0};
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
        for (int i = 0; i < 2; ++i) tmp[i] = st->X[i] + 0.5 * h * k1[i];
        OctaLink_Eval(st, st->t + 0.5 * h, tmp, k2, 0, NULL);
        if (st->status) return;
        for (int i = 0; i < 2; ++i) tmp[i] = st->X[i] + 0.5 * h * k2[i];
        OctaLink_Eval(st, st->t + 0.5 * h, tmp, k3, 0, NULL);
        if (st->status) return;
        for (int i = 0; i < 2; ++i) tmp[i] = st->X[i] + h * k3[i];
        end = OctaLink_IsStepEvent(next) ? nextafter(next, st->t) : next;
        OctaLink_Eval(st, end, tmp, k4, 0, NULL);
        if (st->status) return;
        for (int i = 0; i < 2; ++i) {
            tmp[i] = st->X[i] + (h / 6.0) * (k1[i] + 2.0*k2[i] + 2.0*k3[i] + k4[i]);
            if (!isfinite(tmp[i])) { OctaLink_Error(st, OCTALINK_NONFINITE, 0U); return; }
        }
        for (int i = 0; i < 2; ++i) st->X[i] = tmp[i];
        st->t = next; ++st->step_idx;
        OctaLink_Major(st);
        if (st->status) return;
    }
}
