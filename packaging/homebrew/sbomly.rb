# Template for Formula/sbomly.rb in fullstackspectrum/homebrew-sbomly.
# The release workflow renders it with packaging/homebrew/render_formula.py,
# which fills in the sdist url and sha256 from PyPI. Sbomly has no runtime
# dependencies, so there are no resource blocks. Edit everything else here
# rather than in the tap.
class Sbomly < Formula
  include Language::Python::Virtualenv

  desc "Diff two SBOMs and flag integrity, copyleft, licence and supplier changes"
  homepage "https://github.com/fullstackspectrum/sbomly"
  url "@URL@"
  sha256 "@SHA256@"
  license "Apache-2.0"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/sbomly --version")

    (testpath/"old.json").write <<~JSON
      {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": [
        {"type": "library", "name": "lodash", "version": "4.17.20", "purl": "pkg:npm/lodash@4.17.20"}
      ]}
    JSON
    (testpath/"new.json").write <<~JSON
      {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": [
        {"type": "library", "name": "lodash", "version": "4.17.21", "purl": "pkg:npm/lodash@4.17.21"}
      ]}
    JSON
    output = shell_output("#{bin}/sbomly diff old.json new.json --no-color --fail-on upgraded --html report.html", 1)
    assert_match "lodash", output
    assert_path_exists testpath/"report.html"
  end
end
