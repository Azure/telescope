import os
import argparse
import subprocess

from utils.logger_config import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


def execute(kbench_testnames, results_dir, kubeconfig):
    logger.info(f"""Calling k-bench execute function with
                kbench_testnames: {kbench_testnames},
                results_dir: {results_dir},
                kubeconfig: {kubeconfig}""")
    logger.info("Installing golang")
    subprocess.run(["curl", "-OL", "https://go.dev/dl/go1.24.3.linux-amd64.tar.gz"], check=True)
    subprocess.run(["sudo", "tar", "-C", "/usr/local", "--strip-components=1", "-xzf", "go1.24.3.linux-amd64.tar.gz"], check=True)
    os.environ["PATH"] += os.pathsep + os.path.abspath("/usr/local/go/bin")
    subprocess.run(["go", "version"], check=True)
    subprocess.run(["go", "env"], check=True)
    logger.info("Successfully installed golang")
    logger.info("Cloning k-bench repo")
    subprocess.run(["git", "clone", "https://github.com/anpegush/k-bench"], check=True)
    logger.info("Successfully cloned k-bench repo")
    logger.info("Building k-bench")
    logger.info(f"Current working directory: {os.getcwd()}")
    os.chdir("k-bench")
    logger.info(f"Changed directory to: {os.getcwd()}")
    logger.info(f"Contents of k-bench directory: {os.listdir(os.getcwd())}")
    subprocess.run(["go", "build", "cmd/kbench.go"], check=True)
    os.environ["PATH"] += os.pathsep + os.path.abspath(".")
    logger.info("Successfully built k-bench")
    logger.info("Running k-bench through run.sh:")
    subprocess.run(["mkdir", "-p", results_dir], check=True)
    for testname in kbench_testnames.split(","):
        logger.info(f"Running k-bench test: {testname}")
        subprocess.run(["./run.sh", "-r", f"kbench-cri-{testname}", "-t", testname, "-o", results_dir], check=True)
    logger.info("Successfully ran all k-bench tests")


def main():
    parser = argparse.ArgumentParser(description="Execute k-bench based performance tests.")

    parser.add_argument("kbench_testnames", type=str, help="Comma-separated list of kbench test names")
    parser.add_argument("results_dir", type=str, help="Path to the kbench results directory")
    parser.add_argument("kubeconfig", type=str, help="Path to the kubeconfig file")

    args = parser.parse_args()

    execute(args.kbench_testnames, args.results_dir, args.kubeconfig)

if __name__ == "__main__":
    main()
