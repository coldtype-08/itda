#!/bin/sh
# Fetch the challenge package (synthetic data) into ./challenge. Not vendored in this repo.
set -eu
[ -d challenge/.git ] && { git -C challenge pull --ff-only; exit 0; }
rm -rf challenge
git clone --depth 1 https://github.com/seriousran/k-culture-openshell-challenge.git challenge
