#!/bin/bash

SEMTAG='./tools/semtag'
ACTION=${1:-patch}

git fetch origin --tags

RELEASE_VERSION="$($SEMTAG final -s $ACTION -o)"

echo "Next release version: $RELEASE_VERSION"

if test -f "pyproject.toml"; then
  PROJECT_VERSION=$(echo $RELEASE_VERSION | sed 's/^v//')
  python src/utils/update_project_version.py "$PROJECT_VERSION"

  git config --global user.name 'github-actions[bot]'
  git config --global user.email '41898282+github-actions[bot]@users.noreply.github.com'
  git add pyproject.toml
  git commit -m "Bump version to $RELEASE_VERSION [skip ci]"
  git push
fi

$SEMTAG final -s $ACTION -v "$RELEASE_VERSION"
