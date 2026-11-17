CXXFLAGS ?= -O2 -g -Wall -Wextra -Wpedantic -std=c++20
LDLIBS += -luring

POLICY_SOURCES := policies/policy.cpp policies/round_robin.cpp policies/less_busy.cpp \
                  policies/fixed_delay.cpp policies/budget_limited.cpp policies/single_disk.cpp
SOURCES := mirror.cpp $(POLICY_SOURCES)

mirror: $(SOURCES) policies/policy.h policies/factories.h
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) -o $@ $(SOURCES) $(LDLIBS)

.PHONY: test clean
test: mirror
	python3 tools.py smoke --binary ./mirror

clean:
	$(RM) mirror
