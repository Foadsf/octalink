/* Generated OctaLink C99 model; coefficients are embedded. */
#ifndef OCTALINK_GENERATED_MODEL_H
#define OCTALINK_GENERATED_MODEL_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define OCTALINK_NUM_STATES 4
#define OCTALINK_NUM_OUTPUTS 3
#define OCTALINK_MAX_DT 0.01
#define OCTALINK_MAX_SUBSTEPS 250000U
enum { OCTALINK_OK = 0, OCTALINK_BAD_DT = 1,
       OCTALINK_NONFINITE = 2, OCTALINK_LIMIT = 3 };
typedef struct {
    double t;
    uint32_t step_idx;
    int status;
    uint32_t error_block; /* document ID, or 0 for runtime/time errors */
    double X[4];
    double y_out[3];
    double delay[2], pending[2], zoh[2];
    uint64_t next_hit[2];
    double relay[1];
} OctaLink_State;
/* Init evaluates t=0. Always inspect status before consuming y_out. */
void OctaLink_Init(OctaLink_State *st);
/* Positive finite duration. Events/grid split automatically; final sample is published. */
void OctaLink_Step(OctaLink_State *st, double dt);
/* Next grid/event time capped at stop. stop==t returns t; invalid bounds return NAN. */
double OctaLink_NextTime(const OctaLink_State *st, double stop);
/* y_out groups, in flattened document order; offsets include all sink channels. */
#define OCTALINK_SINK_9_OFFSET 0
#define OCTALINK_SINK_9_CHANNELS 3
#ifdef __cplusplus
}
#endif
#endif
