#include "factories.h"

namespace mirror {
namespace {

class RoundRobinPolicy final : public ReadPolicy {
public:
    unsigned choose_primary(unsigned id, const OutstandingReads&) override {
        return id % 2;
    }
};

}  // namespace

std::unique_ptr<ReadPolicy> make_round_robin_policy() {
    return std::make_unique<RoundRobinPolicy>();
}

}  // namespace mirror
