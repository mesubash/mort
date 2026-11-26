# Homebrew formula template. Copy into a tap repository (github.com/<user>/homebrew-tap, Formula/mort.rb)
# after a tagged release, and fill in sha256. See docs/RELEASE.md.
class Mort < Formula
  include Language::Python::Virtualenv

  desc "Watch long-running jobs and say when they die, stall or finish"
  homepage "https://github.com/mesubash/mort"
  url "https://github.com/mesubash/mort/archive/refs/tags/v0.3.0.tar.gz"
  sha256 "FILL_IN_AT_RELEASE"
  license "MIT"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "mort 0.3.0", shell_output("#{bin}/mort --version")
  end
end
