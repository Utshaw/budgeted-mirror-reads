#include "factories.h"

namespace mirror {
namespace {

class BudgetLimitedPolicy final : public LessBusyPolicy {
    unsigned permit_limit;
    unsigned alternate_threshold;

public:
    BudgetLimitedPolicy(unsigned limit, unsigned threshold)
        : permit_limit(limit), alternate_threshold(threshold) {}

    bool hedges() const override { return true; }

    Hedge hedge(unsigned held_permits, unsigned alternate_outstanding) const override {
        if (held_permits >= permit_limit ||
            (alternate_threshold != 0 && alternate_outstanding >= alternate_threshold))
            return Hedge::none;
        return Hedge::permit;
    }
};

}  // namespace

std::unique_ptr<ReadPolicy> make_budget_policy(unsigned permit_limit, unsigned alternate_threshold) {
    return std::make_unique<BudgetLimitedPolicy>(permit_limit, alternate_threshold);
}

}  // namespace mirror
