#include "first_order.h"
#include <math.h>
#include <stdio.h>
int main(void) {
    OctaLink_State state;
    OctaLink_Init(&state);
    while (state.t < 3.0 && state.status == OCTALINK_OK) {
        double next = OctaLink_NextTime(&state, 3.0);
        OctaLink_Step(&state, next - state.t);
    }
    if (state.status != OCTALINK_OK) return 2;
    printf("CANONICAL C API OUTPUT: %.10f\n", state.y_out[1]);
    return fabs(state.y_out[1] - (1.0-exp(-4.0))) < 1e-7 ? 0 : 1;
}
