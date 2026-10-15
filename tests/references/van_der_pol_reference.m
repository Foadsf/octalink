## Adapted from installed GNU Octave 11.3.0 ode45.m, lines 81-86:
## $OCTAVE_HOME/share/octave/11.3.0/m/ode/ode45.m.
## Source snapshot retained in ode45-upstream.m (GPL-3.0-or-later).
## Independent adaptive ode45 reference for the block model; mu=1, x0=[2;0].
function data = van_der_pol_reference (grid)
  fvdp = @(t,y) [y(2); (1-y(1)^2)*y(2)-y(1)];
  opts = odeset ("RelTol", 1e-10, "AbsTol", 1e-12);
  [t,y] = ode45 (fvdp, grid, [2;0], opts);
  data = [t,y];
endfunction
