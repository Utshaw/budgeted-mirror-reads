CXXFLAGS ?= -O2 -g -Wall -Wextra -Wpedantic -std=c++20
LDLIBS += -luring

mirror: mirror.cpp
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) -o $@ $< $(LDLIBS)

.PHONY: test clean
test: mirror
	python3 tools.py smoke --binary ./mirror

clean:
	$(RM) mirror
