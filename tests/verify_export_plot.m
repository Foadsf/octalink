## Verify the canonical exported script executes and renders without Python.
task_root = fileparts (fileparts (mfilename ("fullpath")));
setenv ("OCTALINK_NO_PLOT", "0");
graphics_toolkit ("gnuplot");
set (0, "defaultfigurevisible", "off");
source (fullfile (task_root, "artifacts", "exports", "first_order.m"));
assert (numel (octalink_results) == 1);
assert (abs (octalink_results(1).values(end,2) - (1-exp(-4))) < 1e-7);
drawnow ();
graphics_toolkit (gcf (), "gnuplot");
print (gcf (), fullfile (task_root, "artifacts", "octave-export-plot.png"), "-dpng");
close all;
printf ("STANDALONE OCTAVE EXPORT OK: analytical output and interactive plot rendered without Python\n");
