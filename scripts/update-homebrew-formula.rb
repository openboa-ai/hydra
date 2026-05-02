#!/usr/bin/env ruby
# frozen_string_literal: true

require "optparse"

options = {
  formula: "Formula/openboa-hydra.rb",
}

parser = OptionParser.new do |parser|
  parser.banner = "usage: update-homebrew-formula.rb --tag TAG --url URL --sha256 SHA256 [--formula PATH]"
  parser.on("--tag TAG", "CalVer release tag, for example v2026.05.02.1") { |value| options[:tag] = value }
  parser.on("--url URL", "Release source asset URL") { |value| options[:url] = value }
  parser.on("--sha256 SHA256", "SHA256 checksum for the release source asset") { |value| options[:sha256] = value }
  parser.on("--formula PATH", "Formula path to update") { |value| options[:formula] = value }
end

parser.parse!

unless options[:tag] && options[:url] && options[:sha256]
  warn parser
  exit 2
end

tag = options.fetch(:tag)
url = options.fetch(:url)
sha256 = options.fetch(:sha256)
formula_path = options.fetch(:formula)

unless tag.match?(/\Av[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[0-9]+\z/)
  abort "tag must match vYYYY.MM.DD.N, got: #{tag}"
end

unless sha256.match?(/\A[a-f0-9]{64}\z/)
  abort "sha256 must be 64 lowercase hex characters"
end

unless url.start_with?("https://") && url.include?("/releases/download/#{tag}/") && url.end_with?(".tar.gz")
  abort "url must be an https release asset URL under /releases/download/#{tag}/"
end

version = tag.delete_prefix("v")
formula = File.read(formula_path)

updated = formula.sub(/^  url .+$/, %(  url "#{url}"))
abort "url line not found in #{formula_path}" if updated == formula

formula = updated

if formula.match?(/^  version ".+"$/)
  formula = formula.sub(/^  version ".+"$/, %(  version "#{version}"))
else
  formula = formula.sub(/^(  url ".+"$)/, "\\1\n  version \"#{version}\"")
end

if formula.match?(/^  sha256 "[a-f0-9]{64}"$/)
  formula = formula.sub(/^  sha256 "[a-f0-9]{64}"$/, %(  sha256 "#{sha256}"))
else
  formula = formula.sub(/^(  version ".+"$)/, "\\1\n  sha256 \"#{sha256}\"")
end

File.write(formula_path, formula)
