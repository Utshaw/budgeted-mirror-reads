#pragma once

#include <array>
#include <memory>
#include <string_view>

namespace mirror {

using OutstandingReads = std::array<unsigned, 2>;

enum class Hedge { none, unmetered, permit };

class ReadPolicy {
public:
    virtual ~ReadPolicy() = default;
    virtual unsigned choose_primary(unsigned id, const OutstandingReads& outstanding) = 0;
    virtual bool hedges() const { return false; }
    virtual Hedge hedge(unsigned, unsigned) const { return Hedge::none; }
};

class LessBusyPolicy : public ReadPolicy {
    unsigned next_tie = 0;

public:
    unsigned choose_primary(unsigned id, const OutstandingReads& outstanding) override;
};

std::unique_ptr<ReadPolicy> make_policy(std::string_view name, unsigned permit_limit,
                                        unsigned alternate_threshold);

}  // namespace mirror
