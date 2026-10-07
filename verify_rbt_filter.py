#!/usr/bin/env python3
"""Quick verification that the RBT-level rubric pattern is now filtered out."""

import sys
sys.path.insert(0, 'd:\\GCEM')

from app import clean_question_text

# Test the exact pattern from the user's input
test_cases = [
    (
        "AM to 11:00 AM Course. unwanted1. Analyze Evaluate Create RBT Levels L1 L2 L3 L4 L5.1. Analyze Evaluate Create RBT Levels L1 L2 L3 L4 L5.",
        "",
        "Exact user-provided rubric header should be filtered to empty"
    ),
    (
        "Analyze Evaluate Create RBT Levels L1 L2 L3 L4 L5",
        "",
        "Isolated Bloom's taxonomy verb sequence should be filtered"
    ),
    (
        "1. Analyze Evaluate Create RBT Levels L1 L2 L3 L4 L5",
        "",
        "Numbered rubric header should be filtered"
    ),
    (
        "What is cloud computing?",
        "What is cloud computing?",
        "Real question should pass through"
    ),
    (
        "Explain the basic Cluster Architecture with a neat diagram.",
        "Explain the basic Cluster Architecture with a neat diagram.",
        "Real question should pass through"
    ),
    (
        "Define Cloud Security. What are top 5 security concerns?",
        "Define Cloud Security. What are top 5 security concerns?",
        "Real multi-part question should pass through"
    ),
]

print("Verifying RBT-level rubric filtering...\n")
passed = 0
failed = 0

for i, (input_text, expected, description) in enumerate(test_cases, 1):
    result = clean_question_text(input_text)
    status = "✓ PASS" if result == expected else "✗ FAIL"
    if result == expected:
        passed += 1
    else:
        failed += 1
    
    print(f"Test {i}: {status}")
    print(f"  Description: {description}")
    if result != expected:
        print(f"  Input:    {input_text[:60]}...")
        print(f"  Expected: {repr(expected)}")
        print(f"  Got:      {repr(result)}")
    print()

print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed")
print(f"{'='*60}")

sys.exit(0 if failed == 0 else 1)
