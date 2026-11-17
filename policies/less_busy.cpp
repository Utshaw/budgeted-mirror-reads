#include "policy.h"

namespace mirror {

unsigned LessBusyPolicy::choose_primary(unsigned, const OutstandingReads& outstanding) {
    if (outstanding[0] == outstanding[1]) {
        const auto selected = next_tie;
        next_tie = 1 - next_tie;
        return selected;
    }
    return outstanding[0] < outstanding[1] ? 0 : 1;
}

}  // namespace mirror
