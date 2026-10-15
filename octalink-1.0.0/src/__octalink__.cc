#include <octave/oct.h>
#include <octave/interpreter.h>
#include <octave/parse.h>
#include <cstdlib>
#include <string>

DEFUN_DLD (__octalink__, args, nargout,
           "-*- texinfo -*-\n\
@deftypefn  {} {} __octalink__ (@var{gui_script_path}, @var{model_file})\n\
Native C++ DLD bridge launching the OctaLink Qt visual modeling environment.\n\
@end deftypefn")
{
  int nargin = args.length ();
  if (nargin < 1)
    error ("__octalink__: expected path to octalink_gui.py");

  std::string script_path = args(0).string_value ();
  std::string model_arg = (nargin >= 2) ? args(1).string_value () : "";

  std::string cmd = "python3 \"" + script_path + "\"";
  if (! model_arg.empty ())
    cmd += " \"" + model_arg + "\"";

#if defined (_WIN32)
  cmd = "start /B " + cmd;
#else
  cmd += " &";
#endif

  int status = std::system (cmd.c_str ());
  return octave_value (status);
}
