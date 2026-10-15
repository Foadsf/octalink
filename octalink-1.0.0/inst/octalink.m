## -*- texinfo -*-
## @deftypefn  {} {} octalink ()
## @deftypefnx {} {} octalink (@var{model_json_path}, @var{python_executable}, @var{mode})
## Launch the OctaLink visual block diagram modeling environment.
## Set OCTALINK_PYTHON to the Python executable containing PyQt6, numpy,
## and matplotlib.  The optional mode "check" runs a model without a GUI
## and returns the child exit status and captured output.
## @end deftypefn

function [status, output] = octalink (model_path = "", python_executable = "", mode = "gui")
  pkg_dir = fileparts (mfilename ("fullpath"));
  gui_script = fullfile (pkg_dir, "octalink_gui.py");

  if (! exist (gui_script, "file"))
    error ("octalink: could not locate octalink_gui.py in %s", pkg_dir);
  endif

  if (! ischar (model_path) || ! ischar (python_executable) || ! any (strcmp (mode, {"gui", "check"})))
    error ("octalink: arguments must be paths and mode must be gui or check");
  endif
  if (isempty (python_executable))
    python_executable = getenv ("OCTALINK_PYTHON");
  endif
  if (isempty (python_executable))
    if (ispc ())
      python_executable = "python";
    else
      python_executable = "python3";
    endif
  endif
  if (strcmp (mode, "check") && isempty (model_path))
    model_path = fullfile (pkg_dir, "examples", "first_order_feedback.json");
  endif
  args = {python_executable, gui_script, "--backend", "octave"};
  if (strcmp (mode, "check"))
    args{end+1} = "--check";
  endif
  if (! isempty (model_path))
    if (! exist (model_path, "file"))
      error ("octalink: model file does not exist: %s", model_path);
    endif
    args{end+1} = model_path;
  endif
  command = strjoin (cellfun (@octalink_quote_arg, args, "UniformOutput", false), " ");
  if (ispc ())
    ## Start with a cmd builtin to preserve a quoted executable and arguments.
    ## Percent/exclamation expansion is excluded by octalink_quote_arg.
    command = ["call ", command];
  endif
  if (strcmp (mode, "check"))
    [status, output] = system (command, true, "sync");
    if (nargout == 0)
      printf ("%s", output);
      if (status != 0)
        error ("octalink: model check failed (child exit %d)", status);
      endif
    endif
  else
    [status, output] = system (command, false, "async");
    printf ("OctaLink launched (process %d).\n", status);
  endif
endfunction

function quoted = octalink_quote_arg (value)
  if (any (value == char(10)) || any (value == char(13)) || any (value == char(0)))
    error ("octalink: invalid control character in path");
  endif
  if (ispc ())
    if (any (value == char(34)) || any (value == "%") || any (value == "!"))
      error ("octalink: quotes, percent and exclamation marks are unsupported in Windows paths");
    endif
    quoted = [char(34), value, char(34)];
  else
    quote_escape = [char(39), char(34), char(39), char(34), char(39)];
    quoted = [char(39), strrep(value, char(39), quote_escape), char(39)];
  endif
endfunction
