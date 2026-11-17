#include "factories.h"

#include <stdexcept>
#include <string>

namespace mirror {

std::unique_ptr<ReadPolicy> make_policy(std::string_view name, unsigned permit_limit,
                                        unsigned alternate_threshold) {
    if (name == "round-robin") return make_round_robin_policy();
    if (name == "less-busy") return std::make_unique<LessBusyPolicy>();
    if (name == "fixed") return make_fixed_policy();
    if (name == "budget") return make_budget_policy(permit_limit, alternate_threshold);
    if (name == "disk-a") return make_single_disk_policy(0);
    if (name == "disk-b") return make_single_disk_policy(1);
    throw std::runtime_error("Unknown policy: " + std::string(name));
}

}  // namespace mirror
