#include <algorithm>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <string>

namespace {

const std::set<std::string> kAllowedCommands = {
    "STOP_MACHINE",
    "LOCKOUT_TAGOUT",
    "SCHEDULE_INSPECTION",
    "NOTIFY_SUPERVISOR",
};

std::string json_escape(const std::string& value) {
    std::ostringstream out;
    for (char ch : value) {
        switch (ch) {
            case '"': out << "\\\""; break;
            case '\\': out << "\\\\"; break;
            case '\n': out << "\\n"; break;
            case '\r': out << "\\r"; break;
            case '\t': out << "\\t"; break;
            default: out << ch; break;
        }
    }
    return out.str();
}

std::map<std::string, std::string> parse_args(int argc, char* argv[]) {
    std::map<std::string, std::string> args;
    for (int i = 1; i < argc; ++i) {
        std::string key = argv[i];
        if (key == "--dry-run") {
            args[key] = "true";
            continue;
        }
        if (key.rfind("--", 0) == 0 && i + 1 < argc) {
            args[key] = argv[++i];
        }
    }
    return args;
}

void write_result(
    const std::string& equipment_id,
    const std::string& command,
    const std::string& status,
    bool dry_run,
    const std::string& message,
    const std::string& correlation_id
) {
    std::cout
        << "{"
        << "\"equipment_id\":\"" << json_escape(equipment_id) << "\","
        << "\"command_type\":\"" << json_escape(command) << "\","
        << "\"status\":\"" << status << "\","
        << "\"dry_run\":" << (dry_run ? "true" : "false") << ","
        << "\"adapter\":\"cpp-control-adapter-v1\","
        << "\"message\":\"" << json_escape(message) << "\","
        << "\"correlation_id\":\"" << json_escape(correlation_id) << "\""
        << "}";
}

}  // namespace

int main(int argc, char* argv[]) {
    const auto args = parse_args(argc, argv);
    const std::string equipment_id = args.count("--equipment-id") ? args.at("--equipment-id") : "";
    const std::string command = args.count("--command") ? args.at("--command") : "";
    const std::string priority = args.count("--priority") ? args.at("--priority") : "P2";
    const std::string reason = args.count("--reason") ? args.at("--reason") : "";
    const std::string correlation_id = args.count("--correlation-id") ? args.at("--correlation-id") : "";
    const bool dry_run = args.count("--dry-run") > 0;

    if (equipment_id.empty() || command.empty()) {
        std::cerr << "equipment-id and command are required\n";
        return 2;
    }

    if (!dry_run) {
        write_result(equipment_id, command, "rejected", false, "Live hardware writes are disabled.", correlation_id);
        return 0;
    }

    if (kAllowedCommands.count(command) == 0) {
        write_result(equipment_id, command, "rejected", true, "Unsupported industrial control command.", correlation_id);
        return 0;
    }

    std::ostringstream message;
    message << "Dry-run accepted " << command << " for " << equipment_id
            << " with priority " << priority << ". Reason: " << reason;
    write_result(equipment_id, command, "accepted", true, message.str(), correlation_id);
    return 0;
}
