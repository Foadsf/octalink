## Octave PNG export for every robotics OctaLink model.
##
## Reads output/csv/<model>/<bid:03d>_sink.csv (written by verify_models.py)
## and writes one PNG per signal channel to output/figures/<model>_sink<bid>_ch<N>.png.
##
## Headless usage:
##   octave-cli --no-gui --quiet --eval "run('scripts/octave_plot_models.m');"

graphics_toolkit("gnuplot");
set(0, "defaultfigurevisible", "off");

script_dir = fileparts(mfilename("fullpath"));
repo_root  = fileparts(script_dir);
csv_root   = fullfile(repo_root, "output", "csv");
fig_root   = fullfile(repo_root, "output", "figures");
if ~exist(fig_root, "dir")
    mkdir(fig_root);
endif

if ~exist(csv_root, "dir")
    error("CSV root not found: %s. Run verify_models.py first.", csv_root);
endif

model_dirs = dir(csv_root);
model_dirs = model_dirs([model_dirs.isdir]);
nfig = 0;

for m = 1:numel(model_dirs)
    mname = char(model_dirs(m).name);
    csvs = dir(fullfile(csv_root, mname, "*_sink.csv"));
    csvs = csvs([csvs.isdir] == false);
    for c = 1:numel(csvs)
        csvfile = char(csvs(c).name);
        bid = str2double(csvfile(1:3));      % "001_sink.csv" -> 1
        csvpath = fullfile(csv_root, mname, csvfile);
        % Skip the header row (col labels), read numeric matrix.
        data = dlmread(csvpath, ",", 1, 0);
        if numel(data) == 0 || size(data, 2) < 2
            continue;
        endif
        t = data(:, 1);
        % Read header for channel labels.
        lbls = {""};
        fid = fopen(csvpath, "r");
        if fid ~= -1
            hdr = fgetl(fid);
            fclose(fid);
            if ischar(hdr) || isstring(hdr)
                lbls = strsplit(char(hdr), ",");
            endif
        endif
        for ch = 2:size(data, 2)
            fig = figure();
            graphics_toolkit(fig, "gnuplot");
            plot(t, data(:, ch), "LineWidth", 1);
            grid on;
            xlabel("t (s)");
            if iscell(lbls) && ch <= numel(lbls) && ~isempty(char(lbls{ch}))
                ylabel(char(lbls{ch}));
            else
                ylabel(sprintf("ch%d", ch - 1));
            endif
            title(sprintf("%s / sink %03d / ch%d", mname, bid, ch - 1));
            png = fullfile(fig_root, sprintf("%s_sink%03d_ch%d.png", ...
                                             mname, bid, ch - 1));
            print(fig, "-dpng", png);
            close(fig);
            nfig = nfig + 1;
        endfor
    endfor
endfor

printf("OCTAVE PNG EXPORT: wrote %d figures to %s\n", nfig, fig_root);
