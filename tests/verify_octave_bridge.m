## Windows or POSIX: run with octave-cli --quiet tests/verify_octave_bridge.m
## All package installs and logs stay in this repository's .tmp/artifacts.
task_root = fileparts (fileparts (mfilename ("fullpath")));
cd (task_root);
pkg_root = fullfile (task_root, ".tmp", "octave-pkg");
mkdir (pkg_root);
pkg ("local_list", fullfile (task_root, ".tmp", "octave-packages"));
pkg ("prefix", pkg_root, fullfile (pkg_root, "arch"));
pkg ("install", fullfile (task_root, "octalink-0.1.0.tar.gz"));
pkg ("load", "octalink");
assert (! isempty (strfind (which ("octalink"), pkg_root)));
printf ("OCTAVE PACKAGE INSTALLED AND LOADED: %s\n", which ("octalink"));

model = fullfile (task_root, "examples", "first_order_feedback.json");
python_executable = getenv ("OCTALINK_PYTHON");
[status, output] = octalink (model, python_executable, "check");
printf ("%s", output);
assert (status == 0);
assert (! isempty (strfind (output, "MODEL CHECK OK")));
printf ("OCTAVE -> PYTHON MODEL CHECK: exit %d\n", status);

bad_model = fullfile (task_root, ".tmp", "bad-model.json");
fid = fopen (bad_model, "w");
fprintf (fid, '{"version":"999","root":{"blocks":[],"wires":[]}}');
fclose (fid);
[bad_status, bad_output] = octalink (bad_model, python_executable, "check");
assert (bad_status != 0);
unlink (bad_model);
printf ("NEGATIVE CONTROL - INVALID MODEL: child exit %d (required nonzero)\n", bad_status);

opts = odeset ("RelTol", 1e-9, "AbsTol", 1e-11);
[t, y] = ode45 (@(t, y) 2 * (1-y), [1, 3], 0, opts);
error_max = max (abs (y - (1-exp(-2*(t-1)))));
assert (error_max < 1e-8);
printf ("OCTAVE ODE45 ANALYTICAL REFERENCE: max error %.3g\n", error_max);
printf ("OCTAVE BRIDGE ACCEPTANCE OK\n");
