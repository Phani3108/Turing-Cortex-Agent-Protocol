# Turing (Cortex Protocol) — Homebrew formula.
#
# Published on the github.com/Phani3108/homebrew-cortex tap.
# Install:  brew tap Phani3108/cortex && brew install cortex-protocol
#
# This formula uses `pipx` under the hood so dependencies land in an
# isolated environment rather than polluting the user's Homebrew Python.
class CortexProtocol < Formula
  include Language::Python::Virtualenv

  desc "Turing — agent governance-as-code. Enforce policies, audit everything, compile to any runtime."
  homepage "https://github.com/Phani3108/Turing-Cortex-Agent-Protocol"
  url "https://files.pythonhosted.org/packages/source/c/cortex-protocol/cortex_protocol-0.4.0.tar.gz"
  # Fill in at release time with `shasum -a 256 cortex_protocol-0.4.0.tar.gz`.
  sha256 "REPLACE_WITH_ACTUAL_SHA_AT_RELEASE_TIME"
  license "MIT"
  head "https://github.com/Phani3108/Turing-Cortex-Agent-Protocol.git", branch: "main"

  depends_on "python@3.12"
  depends_on "node"    # for `npx`-based MCP servers

  resource "pydantic" do
    url "https://files.pythonhosted.org/packages/source/p/pydantic/pydantic-2.10.0.tar.gz"
    sha256 "REPLACE_AT_RELEASE_TIME"
  end

  resource "click" do
    url "https://files.pythonhosted.org/packages/source/c/click/click-8.1.7.tar.gz"
    sha256 "REPLACE_AT_RELEASE_TIME"
  end

  resource "jinja2" do
    url "https://files.pythonhosted.org/packages/source/j/jinja2/Jinja2-3.1.4.tar.gz"
    sha256 "REPLACE_AT_RELEASE_TIME"
  end

  resource "pyyaml" do
    url "https://files.pythonhosted.org/packages/source/p/pyyaml/PyYAML-6.0.2.tar.gz"
    sha256 "REPLACE_AT_RELEASE_TIME"
  end

  # Transitive deps of pydantic are auto-included via the virtualenv build.

  def install
    virtualenv_install_with_resources
  end

  test do
    # Basic sanity — the CLI responds to --version and can `init`.
    assert_match "0.4", shell_output("#{bin}/cortex-protocol --version")
    system "#{bin}/cortex-protocol", "init", "#{testpath}/agent.yaml"
    assert_predicate testpath/"agent.yaml", :exist?
  end
end
