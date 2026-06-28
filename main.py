#!/usr/bin/env python3
"""ARGUS SOC Log Collector — entry point."""

import sys


def main():
    print("ARGUS SOC Log Collector")
    print("  Collectors:")
    print("    - Windows: collector/win/collector.py")
    print("    - Windows Firewall: collector/win/firewall_collector.py")
    print("    - Linux: collector/linux/collector.py")
    print("    - Linux Firewall: collector/linux/firewall_collector.py")
    print("  Producer: producer/producer_.py")
    print()
    print("Run a collector directly, e.g.:")
    print("  python collector/linux/collector.py")
    print("  python collector/win/collector.py")


if __name__ == "__main__":
    sys.exit(main())
