#pragma once

#include "policy.h"

namespace mirror {

std::unique_ptr<ReadPolicy> make_round_robin_policy();
std::unique_ptr<ReadPolicy> make_fixed_policy();
std::unique_ptr<ReadPolicy> make_budget_policy(unsigned permit_limit, unsigned alternate_threshold);
std::unique_ptr<ReadPolicy> make_single_disk_policy(unsigned disk);

}  // namespace mirror
