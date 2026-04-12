#!/bin/bash

set -euxo pipefail

# This script updates the PR description with commands to run the PR locally
# It adds both Docker and uvx commands

# Get the branch name for the PR
BRANCH_NAME=$(gh pr view "$PR_NUMBER" --json headRefName --jq .headRefName)
REPO_SLUG=${REPO:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}
REPO_OWNER_LOWER=$(echo "${REPO_SLUG%%/*}" | tr '[:upper:]' '[:lower:]')
PROJECT_SLUG=$(echo "${REPO_SLUG##*/}" | tr '[:upper:]' '[:lower:]')

RUNTIME_IMAGE="ghcr.io/${REPO_OWNER_LOWER}/runtime:${SHORT_SHA}-nikolaik"
APP_IMAGE="ghcr.io/${REPO_OWNER_LOWER}/app:${SHORT_SHA}"

# Define the Docker command
DOCKER_RUN_COMMAND="docker run -it --rm \
  -p 3000:3000 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --add-host host.docker.internal:host-gateway \
  -e RUNTIME_CONTAINER_IMAGE=${RUNTIME_IMAGE} \
  --name ${PROJECT_SLUG}-app-${SHORT_SHA} \
  ${APP_IMAGE}"

# Define the uvx command
UVX_RUN_COMMAND="uvx --python 3.12 --from git+https://github.com/${REPO_SLUG}@${BRANCH_NAME} grinta"

# Get the current PR body
PR_BODY=$(gh pr view "$PR_NUMBER" --json body --jq .body)

# Prepare the new PR body with both commands
if echo "$PR_BODY" | grep -q "To run this PR locally, use the following command:"; then
  # For existing PR descriptions, use a more robust approach
  # Split the PR body at the "To run this PR locally" section and replace everything after it
  BEFORE_SECTION=$(echo "$PR_BODY" | sed '/To run this PR locally, use the following command:/,$d')
  NEW_PR_BODY=$(cat <<EOF
${BEFORE_SECTION}

To run this PR locally, use the following command:

GUI with Docker:
\`\`\`
${DOCKER_RUN_COMMAND}
\`\`\`

CLI with uvx:
\`\`\`
${UVX_RUN_COMMAND}
\`\`\`
EOF
)
else
  # For new PR descriptions: use heredoc safely without indentation
  NEW_PR_BODY=$(cat <<EOF
$PR_BODY

---

To run this PR locally, use the following command:

GUI with Docker:
\`\`\`
${DOCKER_RUN_COMMAND}
\`\`\`

CLI with uvx:
\`\`\`
${UVX_RUN_COMMAND}
\`\`\`
EOF
)
fi

# Update the PR description
echo "Updating PR description with Docker and uvx commands"
gh pr edit "$PR_NUMBER" --body "$NEW_PR_BODY"
