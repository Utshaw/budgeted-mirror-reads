#include "factories.h"

namespace mirror {
namespace {

class SingleDiskPolicy final : public ReadPolicy {
    unsigned disk;

public:
    explicit SingleDiskPolicy(unsigned selected_disk) : disk(selected_disk) {}

    unsigned choose_primary(unsigned, const OutstandingReads&) override { return disk; }
};

}  // namespace

std::unique_ptr<ReadPolicy> make_single_disk_policy(unsigned disk) {
    return std::make_unique<SingleDiskPolicy>(disk);
}

}  // namespace mirror
