package main

import (
	"bytes"
	"encoding/json"
	"testing"
)

func TestVersion(t *testing.T) {
	originalVersion, originalCommit := version, commit
	t.Cleanup(func() { version, commit = originalVersion, originalCommit })
	version, commit = "v0.1.0", "0123456789abcdef"

	var output bytes.Buffer
	if err := run([]string{"version"}, &output); err != nil {
		t.Fatalf("run(version) error = %v", err)
	}
	var got versionInfo
	if err := json.Unmarshal(output.Bytes(), &got); err != nil {
		t.Fatalf("decode version output: %v", err)
	}
	if got.Version != version || got.Commit != commit {
		t.Fatalf("version output = %+v, want version=%q commit=%q", got, version, commit)
	}
}

func TestVersionRejectsArguments(t *testing.T) {
	if err := run([]string{"version", "extra"}, &bytes.Buffer{}); err == nil {
		t.Fatal("run(version extra) succeeded, want error")
	}
}

func TestRunRequiresCommand(t *testing.T) {
	if err := run(nil, &bytes.Buffer{}); err == nil {
		t.Fatal("run(nil) succeeded, want usage error")
	}
}
