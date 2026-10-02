#!/usr/bin/env bash
# sr11c_digits_only.sh — SR11c: the "digits only" rule, checked mechanically
# over the WORKING diff (or a commit range, "$@" is passed to git diff):
# the removed and the added lines, with every digit deleted, must be the same
# multiset, and every changed file must remove as many lines as it adds.
# Prints DIGITS-ONLY OK, or the offending lines.  Nothing numeric.
#   evidence/qwen9b/sr/sr11c_digits_only.sh [git-diff args]
set -u
cd /home/cah/r2d2/code/fpga/fable5_llm || exit 1
T=$(mktemp -d /tmp/sr11c_dig.XXXXXX); trap 'rm -rf "$T"' EXIT
D=(git diff -U0 --no-color --output-indicator-old='<' --output-indicator-new='>')
"${D[@]}" "$@" | grep -v -e '^--- ' -e '^+++ ' | grep '^<' | sed 's/^<//; s/[0-9]//g' | sort > "$T/m"
"${D[@]}" "$@" | grep -v -e '^--- ' -e '^+++ ' | grep '^>' | sed 's/^>//; s/[0-9]//g' | sort > "$T/p"
echo "files $(git diff --name-only "$@" | wc -l)   removed lines $(wc -l < "$T/m")   added lines $(wc -l < "$T/p")"
bad=$(git diff --numstat "$@" | awk '$1!=$2')
[ -n "$bad" ] && { echo "UNEQUAL line counts:"; echo "$bad"; }
if diff "$T/m" "$T/p" > "$T/d" && [ -z "$bad" ]; then echo "DIGITS-ONLY OK"; exit 0; fi
sed 's/^/  /' "$T/d" | head -40; echo "NOT DIGITS-ONLY"; exit 1
