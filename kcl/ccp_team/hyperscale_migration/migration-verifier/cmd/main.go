package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"github.com/Azure/telescope/kcl/ccp_team/hyperscale_migration/migration-verifier/internal/workload"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/tools/clientcmd"
)

var (
	version = "dev"
	commit  = "unknown"
)

type versionInfo struct {
	Version string `json:"version"`
	Commit  string `json:"commit"`
}

func main() {
	if err := run(os.Args[1:], os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run(args []string, output io.Writer) error {
	if len(args) < 1 {
		return errorsUsage()
	}
	switch args[0] {
	case "ingest":
		return ingest(args[1:], output)
	case "verify":
		return verify(args[1:], output)
	case "version":
		if len(args) != 1 {
			return fmt.Errorf("version does not accept arguments")
		}
		return json.NewEncoder(output).Encode(versionInfo{Version: version, Commit: commit})
	default:
		return fmt.Errorf("unknown command %q", args[0])
	}
}

func errorsUsage() error {
	return fmt.Errorf("usage: hyperscale-migration-verifier <ingest|verify|version> [flags]")
}

func ingest(args []string, output io.Writer) error {
	flags := flag.NewFlagSet("ingest", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	kubeconfig := flags.String("kubeconfig", defaultKubeconfig(), "path to kubeconfig")
	manifestPath := flags.String("manifest", "hyperscale-migration-manifest.json", "output manifest path")
	if err := flags.Parse(args); err != nil {
		return err
	}
	client, err := newKubernetesClient(*kubeconfig)
	if err != nil {
		return err
	}
	manifest, ingestErr := workload.NewRunner(client).Ingest(context.Background(), workload.DefaultConfig())
	if err := workload.WriteManifest(*manifestPath, manifest); err != nil {
		return err
	}
	if ingestErr != nil {
		return ingestErr
	}
	_, err = fmt.Fprintf(output, "created %d objects with %d logical payload bytes; manifest=%s\n", len(manifest.Objects), manifest.LogicalPayloadBytes, *manifestPath)
	return err
}

func verify(args []string, output io.Writer) error {
	flags := flag.NewFlagSet("verify", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	kubeconfig := flags.String("kubeconfig", defaultKubeconfig(), "path to kubeconfig")
	manifestPath := flags.String("manifest", "hyperscale-migration-manifest.json", "input manifest path")
	if err := flags.Parse(args); err != nil {
		return err
	}
	manifest, err := workload.ReadManifest(*manifestPath)
	if err != nil {
		return err
	}
	client, err := newKubernetesClient(*kubeconfig)
	if err != nil {
		return err
	}
	runner := workload.NewRunner(client)
	for _, spec := range manifest.Specs {
		if _, err := fmt.Fprintf(output, "verifying %s resources: expected=%d\n", spec.Kind, spec.Count); err != nil {
			return err
		}
	}
	deadline := time.Now().Add(workload.DefaultVerifyTimeout)
	for {
		err = runner.Verify(context.Background(), manifest)
		if err == nil {
			_, writeErr := fmt.Fprintf(output, "verified %d objects with %d logical payload bytes\n", len(manifest.Objects), manifest.LogicalPayloadBytes)
			return writeErr
		}
		if time.Now().Add(workload.DefaultVerifyPollInterval).After(deadline) {
			return fmt.Errorf("verification did not succeed within %s: %w", workload.DefaultVerifyTimeout, err)
		}
		fmt.Fprintf(output, "verification pending: %v\n", err)
		time.Sleep(workload.DefaultVerifyPollInterval)
	}
}

func defaultKubeconfig() string {
	if value := os.Getenv("KUBECONFIG"); value != "" {
		return value
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, ".kube", "config")
}

func newKubernetesClient(kubeconfig string) (kubernetes.Interface, error) {
	config, err := clientcmd.BuildConfigFromFlags("", kubeconfig)
	if err != nil {
		return nil, fmt.Errorf("load kubeconfig: %w", err)
	}
	config.QPS = workload.DefaultQPS
	config.Burst = workload.DefaultBurst
	return kubernetes.NewForConfig(config)
}
