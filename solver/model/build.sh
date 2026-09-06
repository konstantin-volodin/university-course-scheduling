#!/usr/bin/env bash
# Builds manuscript.pdf from manuscript.tex.
# Uses a local pdflatex if one is installed, otherwise a texlive container.
set -euo pipefail
cd "$(dirname "$0")"

if command -v pdflatex >/dev/null; then
    pdflatex -interaction=nonstopmode -halt-on-error manuscript.tex
else
    docker run --rm -v "$PWD:/doc" -w /doc -u "$(id -u):$(id -g)" \
        texlive/texlive:latest \
        pdflatex -interaction=nonstopmode -halt-on-error manuscript.tex
fi

rm -f manuscript.aux manuscript.log manuscript.out
echo "wrote $PWD/manuscript.pdf"
