# Homebrew formula for Grinta
#
# Maintainer note: bump `version` and `sha256` on each release.
# `brew create --python https://files.pythonhosted.org/.../grinta-ai-X.Y.Z.tar.gz`
# can scaffold an updated version. Keep this file as the canonical template.
class Grinta < Formula
  include Language::Python::Virtualenv

  desc "Autonomous local-first CLI coding agent"
  homepage "https://github.com/josephsenior/Grinta-Coding-Agent"
  url "https://files.pythonhosted.org/packages/source/g/grinta-ai/grinta-ai-0.55.0.tar.gz"
  sha256 "REPLACE_ON_RELEASE_WITH_PYPI_SDIST_SHA256"
  license "MIT"

  depends_on "python@3.12"
  depends_on "ripgrep"

  def install
    virtualenv_install_with_resources
    # Expose the canonical entry point as `grinta`.
    (bin/"grinta").write <<~SH
      #!/usr/bin/env bash
      exec "#{libexec}/bin/python" -m backend.cli.entry "$@"
    SH
    chmod 0755, bin/"grinta"
  end

  test do
    assert_match "grinta", shell_output("#{bin}/grinta --help")
  end
end
