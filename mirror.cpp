#include <liburing.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#include <array>
#include <cerrno>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <csignal>
#include <cstring>
#include <fstream>
#include <iostream>
#include <list>
#include <memory>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

constexpr unsigned block_size = 4096;
using Clock = std::chrono::steady_clock;
volatile std::sig_atomic_t stop_requested = 0;
void stop(int) { stop_requested = 1; }

unsigned number(const char* value, unsigned min, unsigned max) {
    unsigned result = 0;
    const char* end = value + std::strlen(value);
    auto [last, error] = std::from_chars(value, end, result);
    if (error != std::errc{} || last != end || result < min || result > max)
        throw std::runtime_error(std::string("Invalid numeric argument: ") + value);
    return result;
}

void check(int result, const char* operation) {
    if (result < 0)
        throw std::runtime_error(std::string(operation) + ": " + std::strerror(-result));
}

struct File {
    int fd;
    struct stat info{};
    explicit File(const char* path) : fd(open(path, O_RDONLY | O_DIRECT | O_CLOEXEC)) {
        if (fd < 0) check(-errno, path);
        if (fstat(fd, &info) < 0) {
            int error = errno;
            close(fd);
            check(-error, "fstat");
        }
    }
    ~File() { close(fd); }
};

enum class Policy { round_robin, less_busy, fixed, budget };
Policy parse_policy(const std::string& name) {
    if (name == "round-robin") return Policy::round_robin;
    if (name == "less-busy") return Policy::less_busy;
    if (name == "fixed") return Policy::fixed;
    if (name == "budget") return Policy::budget;
    throw std::runtime_error("Unknown policy: " + name);
}

struct Request {
    unsigned id;
    uint64_t block;
    int64_t start;
    int64_t logical_end = -1;
    int64_t drained = -1;
    unsigned original;
    unsigned pending = 0;
    unsigned issued = 0;
    int winner = -1;
    bool permit = false;
};

struct Replica {
    Request* request;
    unsigned disk;
    unsigned attempt;
    int64_t start;
    unsigned permits_at_submit;
    alignas(block_size) std::array<unsigned char, block_size> data;
};

struct Completion {
    unsigned request_id, disk, attempt;
    int64_t done, start;
    int result;
    bool valid, winner;
    unsigned permits_at_submit, permits_after_completion;
};

class Run {
    std::array<int, 2> files;
    uint64_t blocks;
    Policy policy;
    unsigned count, depth, delay_us, budget, threshold;
    std::mt19937_64 rng;
    std::vector<Request> requests;
    std::vector<Completion> completions;
    std::list<Request*> waiting;
    std::vector<std::unique_ptr<Replica>> in_flight;
    std::array<unsigned, 2> outstanding{};
    unsigned permits = 0;
    unsigned errors = 0;
    uint64_t bytes_read = 0;
    Clock::time_point origin = Clock::now();
    io_uring ring{};

    int64_t now() const {
        return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - origin).count();
    }

    unsigned choose_disk(unsigned id) const {
        if (policy == Policy::round_robin || outstanding[0] == outstanding[1]) return id % 2;
        return outstanding[0] < outstanding[1] ? 0 : 1;
    }

    bool room() const { return in_flight.size() < 4 * depth; }

    void submit(Request& request, unsigned disk) {
        auto* sqe = io_uring_get_sqe(&ring);
        if (!sqe) throw std::runtime_error("Submission ring is full");
        auto replica = std::make_unique<Replica>();
        replica->request = &request;
        replica->disk = disk;
        replica->attempt = ++request.issued;
        replica->start = now();
        replica->permits_at_submit = permits;
        io_uring_prep_read(sqe, files[disk], replica->data.data(), block_size,
                           request.block * block_size);
        io_uring_sqe_set_data(sqe, replica.get());
        in_flight.push_back(std::move(replica));
        ++request.pending;
        ++outstanding[disk];
    }

    bool valid_data(const Replica& replica) const {
        const uint64_t block = replica.request->block;
        std::array<unsigned char, 8> expected{};
        for (unsigned i = 0; i < expected.size(); ++i)
            expected[i] = static_cast<unsigned char>(block >> (8 * i));
        for (unsigned i = 0; i < block_size; i += expected.size())
            if (std::memcmp(replica.data.data() + i, expected.data(), expected.size()) != 0)
                return false;
        return true;
    }

    void complete(io_uring_cqe* cqe) {
        const auto done = now();
        auto* replica = static_cast<Replica*>(io_uring_cqe_get_data(cqe));
        auto& request = *replica->request;
        const int result = cqe->res;
        io_uring_cqe_seen(&ring, cqe);
        --request.pending;
        --outstanding[replica->disk];
        if (result > 0) bytes_read += static_cast<unsigned>(result);
        const bool valid = result == block_size && valid_data(*replica);
        const bool winner = valid && request.logical_end < 0;
        if (winner) request.winner = static_cast<int>(replica->disk);
        if (request.logical_end < 0 && (winner || request.pending == 0)) {
            request.logical_end = done;
            if (!winner) ++errors;
        }
        if (request.pending == 0) {
            request.drained = done;
            if (request.permit) --permits;
        }
        completions.push_back({request.id, replica->disk, replica->attempt,
                               done, replica->start, result, valid, winner, replica->permits_at_submit, permits});
        for (auto& entry : in_flight) {
            if (entry.get() == replica) {
                if (&entry != &in_flight.back()) entry = std::move(in_flight.back());
                in_flight.pop_back();
                break;
            }
        }
    }

    void reap() {
        io_uring_cqe* cqe;
        while (io_uring_peek_cqe(&ring, &cqe) == 0) complete(cqe);
        waiting.remove_if([](const Request* request) { return request->logical_end >= 0; });
    }

    int64_t schedule() {
        int64_t next_due = -1;
        if (stop_requested || (policy != Policy::fixed && policy != Policy::budget)) return next_due;
        for (auto* request : waiting) {
            if (!room()) break;
            if (request->issued == 2) continue;
            const unsigned alternate = 1 - request->original;
            if (policy == Policy::budget &&
                (permits >= budget || (threshold != 0 && outstanding[alternate] >= threshold)))
                continue;
            const auto due = request->start + 1000LL * delay_us;
            if (now() < due) {
                if (next_due < 0) next_due = due;
                continue;
            }
            // A visible completion takes precedence over a due hedge.
            io_uring_cqe* ready;
            if (io_uring_peek_cqe(&ring, &ready) == 0) return now();
            if (policy == Policy::budget) {
                ++permits;
                request->permit = true;
            }
            submit(*request, alternate);
        }
        return next_due;
    }

public:
    Run(const File& a, const File& b, Policy strategy, unsigned operations, unsigned concurrency,
        unsigned delay, unsigned limit, unsigned alternate_limit, unsigned seed)
        : files{a.fd,b.fd}, blocks(a.info.st_size / block_size), policy(strategy),
          count(operations), depth(concurrency), delay_us(delay), budget(limit),
          threshold(alternate_limit), rng(seed) {
        requests.reserve(count);
        completions.reserve(2 * count);
        in_flight.reserve(4 * depth);
        check(io_uring_queue_init(4 * depth, &ring, 0), "io_uring_queue_init");
    }
    ~Run() { io_uring_queue_exit(&ring); }

    void execute() {
        std::uniform_int_distribution<uint64_t> pick(0, blocks - 1);
        origin = Clock::now();
        for (;;) {
            reap();
            if ((stop_requested || requests.size() == count) && in_flight.empty()) break;
            // Give overdue hedges first access to newly freed physical slots.
            auto due = schedule();
            while (!stop_requested && waiting.size() < depth && requests.size() < count && room()) {
                unsigned id = static_cast<unsigned>(requests.size());
                requests.push_back(Request{.id = id, .block = pick(rng), .start = now(),
                                           .original = choose_disk(id)});
                auto& request = requests.back();
                waiting.push_back(&request);
                submit(request, request.original);
            }
            // Schedule newly admitted requests too, including a zero hedge delay.
            const auto new_due = schedule();
            if (new_due >= 0 && (due < 0 || new_due < due)) due = new_due;
            int submitted;
            do {
                submitted = io_uring_submit(&ring);
                if (submitted == -EINTR) continue;
                check(submitted, "io_uring_submit");
            } while (submitted == -EINTR || io_uring_sq_ready(&ring));

            if (in_flight.empty()) continue;
            io_uring_cqe* cqe;
            int result;
            if (due >= 0 && room()) {
                const auto remaining = due - now();
                if (remaining <= 0) continue;
                __kernel_timespec timeout{remaining / 1000000000, remaining % 1000000000};
                result = io_uring_wait_cqe_timeout(&ring, &cqe, &timeout);
                if (result == -ETIME) continue;
            } else {
                result = io_uring_wait_cqe(&ring, &cqe);
            }
            if (result == -EINTR) continue;
            check(result, "waiting for completions");
            complete(cqe);
        }
    }

    int write_logs(const std::string& prefix) const {
        std::ofstream logical(prefix + "-logical.csv");
        std::ofstream replica(prefix + "-replica.csv");
        logical.exceptions(std::ios::failbit | std::ios::badbit);
        replica.exceptions(std::ios::failbit | std::ios::badbit);
        logical << "id,offset,start_ns,end_ns,drained_ns,winner,issued,permit\n";
        replica << "id,attempt,disk,start_ns,end_ns,result,valid,winner,permits_at_submit,permits_after_completion\n";
        for (const auto& r : requests)
            logical << r.id << ',' << r.block * block_size << ',' << r.start << ','
                    << r.logical_end << ',' << r.drained << ',' << r.winner << ','
                    << r.issued << ',' << r.permit << '\n';
        for (const auto& c : completions)
            replica << c.request_id << ',' << c.attempt << ',' << c.disk << ','
                    << c.start << ',' << c.done << ',' << c.result << ',' << c.valid << ','
                    << c.winner << ',' << c.permits_at_submit << ',' << c.permits_after_completion << '\n';
        logical.close();
        replica.close();
        std::cout << "Logical reads: " << requests.size() << ", failed: " << errors
                  << ", replica reads drained: " << completions.size()
                  << ", replica bytes: " << bytes_read << '\n';
        if (stop_requested) return 130;
        return errors == 0 ? 0 : 2;
    }
};

int main(int argc, char** argv) {
    if (argc != 11) {
        std::cerr << "Usage: mirror A B MODE COUNT DEPTH DELAY_US PERMITS THRESHOLD SEED LOG_PREFIX\n"
                  << "MODE: round-robin, less-busy, fixed, budget. THRESHOLD=0 disables the threshold.\n";
        return 1;
    }
    try {
        File a(argv[1]), b(argv[2]);
        if (!S_ISREG(a.info.st_mode) || !S_ISREG(b.info.st_mode) ||
            a.info.st_size < block_size || a.info.st_size != b.info.st_size ||
            a.info.st_size % block_size != 0)
            throw std::runtime_error("Replica files must be nonempty regular files of equal, aligned size");
        if (a.info.st_dev == b.info.st_dev && a.info.st_ino == b.info.st_ino)
            throw std::runtime_error("Use two distinct replica files");
        Run run(a, b, parse_policy(argv[3]), number(argv[4], 1, 1000000),
                number(argv[5], 1, 1024), number(argv[6], 0, 10000000),
                number(argv[7], 0, 4096), number(argv[8], 0, 4096),
                number(argv[9], 0, UINT32_MAX));
        std::signal(SIGINT, stop);
        std::signal(SIGTERM, stop);
        run.execute();
        return run.write_logs(argv[10]);
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
