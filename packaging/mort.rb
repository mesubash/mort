# Homebrew formula. Lives in github.com/mesubash/homebrew-tap as Formula/mort.rb; see docs/RELEASE.md.
# mort is plain Python with no dependencies, so the package is copied and run with Homebrew's Python.
class Mort < Formula
  desc "Watch long-running jobs and say when they die, stall or finish"
  homepage "https://github.com/mesubash/mort"
  url "https://github.com/mesubash/mort/archive/refs/tags/v0.3.2.tar.gz"
  sha256 "FILL_IN_AT_RELEASE"
  license "MIT"

  depends_on "python@3.14"

  def install
    libexec.install "mort"
    (bin/"mort").write <<~EOS
      #!/bin/bash
      PYTHONPATH="#{libexec}" exec "#{Formula["python@3.14"].opt_bin}/python3.14" -m mort "$@"
    EOS
  end

  test do
    assert_match "mort #{version}", shell_output("#{bin}/mort --version")
  end
end
