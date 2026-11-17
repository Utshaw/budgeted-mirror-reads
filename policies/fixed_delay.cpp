#include "factories.h"

namespace mirror {
namespace {

class FixedDelayPolicy final : public LessBusyPolicy {
public:
    bool hedges() const override { return true; }
    Hedge hedge(unsigned, unsigned) const override { return Hedge::unmetered; }
};

}  // namespace

std::unique_ptr<ReadPolicy> make_fixed_policy() {
    return std::make_unique<FixedDelayPolicy>();
}

}  // namespace mirror
