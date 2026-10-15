MKOCTFILE ?= mkoctfile

all: __octalink__.oct

__octalink__.oct: __octalink__.cc
	$(MKOCTFILE) __octalink__.cc -o __octalink__.oct

clean:
	rm -f *.o *.oct
