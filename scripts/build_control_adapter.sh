#!/usr/bin/env bash
set -euo pipefail

mkdir -p build
clang++ -std=c++17 -O2 -Wall -Wextra -pedantic cpp/control_adapter.cpp -o build/control_adapter
echo "Built build/control_adapter"
